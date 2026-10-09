-- Planner bot schema (Supabase / Postgres)
-- Access model: the bot talks to PostgREST with the anon key and an
-- `x-bot-secret` header. Every table is RLS-protected by a policy that
-- compares that header with a secret stored in the non-exposed `private` schema.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.config (k text primary key, v text not null);

create or replace function private.bot_ok() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from private.config
     where k = 'bot_secret'
       and v = coalesce(current_setting('request.headers', true)::json ->> 'x-bot-secret', '')
  );
$$;
grant usage on schema private to anon;
grant execute on function private.bot_ok() to anon;

create table if not exists public.users (
  id             bigint primary key,            -- Telegram user id
  first_name     text,
  tz             text    not null default 'Europe/Kyiv',
  morning_on     boolean not null default true,
  morning_time   text    not null default '09:00',
  evening_on     boolean not null default true,
  evening_time   text    not null default '21:00',
  auto_rollover  boolean not null default true,
  last_morning   date,
  last_evening   date,
  last_rollover  date,
  created_at     timestamptz not null default now()
);

create table if not exists public.tasks (
  id         bigserial primary key,
  user_id    bigint not null references public.users(id) on delete cascade,
  title      text   not null,
  due        date   not null,
  priority   smallint not null default 0,         -- 0 none, 1 low, 2 mid, 3 high
  tag        text,
  done       boolean not null default false,
  done_day   date,                                -- local date when completed
  remind_at  timestamptz,
  reminded   boolean not null default false,
  moved      smallint not null default 0,         -- how many times postponed
  created_at timestamptz not null default now()
);
create index if not exists tasks_user_due on public.tasks(user_id, due);
create index if not exists tasks_user_doneday on public.tasks(user_id, done_day) where done;
create index if not exists tasks_pending_rem on public.tasks(remind_at) where not reminded and not done;

create table if not exists public.notes (
  id         bigserial primary key,
  user_id    bigint not null references public.users(id) on delete cascade,
  day        date   not null,
  body       text   not null,
  created_at timestamptz not null default now()
);
create index if not exists notes_user_day on public.notes(user_id, day);

create table if not exists public.fsm (
  user_id bigint not null,
  chat_id bigint not null,
  state   text,
  data    jsonb not null default '{}'::jsonb,
  primary key (user_id, chat_id)
);

do $$
declare t text;
begin
  foreach t in array array['users','tasks','notes','fsm'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists bot_all on public.%I', t);
    execute format('create policy bot_all on public.%I for all to anon using ((select private.bot_ok())) with check ((select private.bot_ok()))', t);
    execute format('revoke all on public.%I from authenticated', t);
  end loop;
end $$;

-- Move undone overdue tasks to today (once per day per user)
create or replace function public.rollover(p_uid bigint, p_today date) returns int
language plpgsql set search_path = public as $$
declare n int := 0; v_auto boolean;
begin
  select auto_rollover into v_auto from users where id = p_uid;
  if coalesce(v_auto, false) then
    update tasks set due = p_today, moved = moved + 1
     where user_id = p_uid and not done and due < p_today;
    get diagnostics n = row_count;
  end if;
  update users set last_rollover = p_today where id = p_uid;
  return n;
end $$;

-- Postpone all undone tasks of one day to another day
create or replace function public.postpone_undone(p_uid bigint, p_from date, p_to date) returns int
language plpgsql set search_path = public as $$
declare n int;
begin
  update tasks
     set due = p_to,
         moved = moved + 1,
         remind_at = case when remind_at is not null and not reminded
                          then remind_at + (p_to - p_from) * interval '1 day'
                          else remind_at end
   where user_id = p_uid and due = p_from and not done;
  get diagnostics n = row_count;
  return n;
end $$;

-- Atomically take reminders that are due
create or replace function public.claim_reminders() returns setof public.tasks
language sql set search_path = public as $$
  update tasks set reminded = true
   where remind_at <= now() and not reminded and not done
  returning *;
$$;

-- Statistics for one user
create or replace function public.user_stats(p_uid bigint, p_today date) returns jsonb
language plpgsql stable set search_path = public as $$
declare r jsonb; v_streak int := 0; d date := p_today;
begin
  if not exists (select 1 from tasks where user_id = p_uid and done and done_day = d) then
    d := d - 1;
  end if;
  while exists (select 1 from tasks where user_id = p_uid and done and done_day = d) loop
    v_streak := v_streak + 1;
    d := d - 1;
  end loop;

  select jsonb_build_object(
    'today_total', (select count(*) from tasks where user_id = p_uid and due = p_today),
    'today_done',  (select count(*) from tasks where user_id = p_uid and due = p_today and done),
    'week_total',  (select count(*) from tasks where user_id = p_uid and due between p_today - 6 and p_today),
    'week_done',   (select count(*) from tasks where user_id = p_uid and due between p_today - 6 and p_today and done),
    'all_done',    (select count(*) from tasks where user_id = p_uid and done),
    'notes',       (select count(*) from notes where user_id = p_uid),
    'best',        coalesce((select max(c) from (select count(*) c from tasks
                              where user_id = p_uid and done group by done_day) x), 0),
    'streak',      v_streak,
    'days',        (select jsonb_agg(jsonb_build_object(
                              'd', g::date,
                              'n', (select count(*) from tasks t where t.user_id = p_uid and t.done and t.done_day = g::date))
                            order by g)
                      from generate_series(p_today - 6, p_today, interval '1 day') g),
    'tags',        coalesce((select jsonb_agg(jsonb_build_object('tag', tag, 'n', n) order by n desc)
                      from (select tag, count(*) n from tasks
                             where user_id = p_uid and done and tag is not null
                               and done_day between p_today - 6 and p_today
                             group by tag order by n desc limit 5) x), '[]'::jsonb)
  ) into r;
  return r;
end $$;

revoke execute on function public.rollover(bigint, date) from public, authenticated;
revoke execute on function public.postpone_undone(bigint, date, date) from public, authenticated;
revoke execute on function public.claim_reminders() from public, authenticated;
revoke execute on function public.user_stats(bigint, date) from public, authenticated;
grant execute on function public.rollover(bigint, date) to anon;
grant execute on function public.postpone_undone(bigint, date, date) to anon;
grant execute on function public.claim_reminders() to anon;
grant execute on function public.user_stats(bigint, date) to anon;
