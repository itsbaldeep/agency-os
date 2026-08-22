BEGIN;

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS parent_task_id integer REFERENCES tasks(id) ON DELETE SET NULL;

ALTER TABLE suggestions
    ADD COLUMN IF NOT EXISTS execution_task_id integer REFERENCES tasks(id) ON DELETE SET NULL;

ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS publish_task_id integer REFERENCES tasks(id) ON DELETE SET NULL;

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS task_id integer REFERENCES tasks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_execution_task_id ON suggestions(execution_task_id);
CREATE INDEX IF NOT EXISTS idx_content_items_publish_task_id ON content_items(publish_task_id);
CREATE INDEX IF NOT EXISTS idx_approvals_task_id ON approvals(task_id);

COMMIT;
