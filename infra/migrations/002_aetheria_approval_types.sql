-- 002_aetheria_approval_types.sql
-- Add the three Aetheria-specific approval types used by the loop automation
-- (docs/AGENCY_INTEGRATION.md §3). Purely additive — no data loss.
--   aetheria_screens    — each screenshot set needing human review
--   aetheria_gate       — milestone sign-off gates (pauses the loop)
--   aetheria_human_todo — new HUMAN_TODO item (VRoid models, UI art, keys)
--
-- ALTER TYPE ... ADD VALUE is non-transactional pre-PG12; on PG16 it is safe
-- inside a transaction block but each ADD VALUE must be its own statement.

ALTER TYPE public.approval_type ADD VALUE IF NOT EXISTS 'aetheria_screens';
ALTER TYPE public.approval_type ADD VALUE IF NOT EXISTS 'aetheria_gate';
ALTER TYPE public.approval_type ADD VALUE IF NOT EXISTS 'aetheria_human_todo';
