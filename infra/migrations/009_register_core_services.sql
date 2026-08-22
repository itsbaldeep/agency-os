BEGIN;

INSERT INTO services (project_id,name,kind,container,port,status)
VALUES
  (14,'agency-worker','systemd',NULL,NULL,'running'),
  (14,'agency-bot','systemd',NULL,NULL,'running'),
  (14,'opencode','systemd',NULL,4096,'running'),
  (14,'caddy','systemd',NULL,443,'running'),
  (14,'minio','object-storage','agency-minio',9010,'running'),
  (10,'website','web','deployden-site',3014,'running')
ON CONFLICT (project_id,name) DO UPDATE
SET kind=EXCLUDED.kind,container=EXCLUDED.container,port=EXCLUDED.port,status=EXCLUDED.status;

COMMIT;
