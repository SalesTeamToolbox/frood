---
name: database-migration
description: Plan and execute database schema migrations safely with rollback support.
always: false
task_types: [coding]
requirements_bins: [git]
---

# Database Migration

## Core Principles

1. **Every schema change must be a versioned migration**: Never modify the database manually in production. All changes go through migration files tracked in version control.
2. **Migrations must be backwards compatible**: The old application code should still work during the migration window. This enables zero-downtime deployments.
3. **Make small, incremental changes**: One concern per migration. Do not combine unrelated changes into a single migration file.
4. **Always test on a staging environment first**: Run migrations against a copy of production data before deploying to production.

## Migration Frameworks

### Python
- **Alembic** (SQLAlchemy): Generate migrations with `alembic revision --autogenerate -m "description"`. Review auto-generated files before applying. Run with `alembic upgrade head`, rollback with `alembic downgrade -1`.
- **Django Migrations**: Auto-detect model changes with `python manage.py makemigrations`. Apply with `python manage.py migrate`. Rollback with `python manage.py migrate app_name 0003_previous`.

### JavaScript / TypeScript
- **Prisma Migrate**: Define schema in `schema.prisma`, generate with `prisma migrate dev --name description`. Apply in production with `prisma migrate deploy`.
- **Knex.js**: Create with `knex migrate:make migration_name`. Each file exports `up()` and `down()` functions. Run with `knex migrate:latest`, rollback with `knex migrate:rollback`.
- **TypeORM**: Supports auto-generation from entity changes. Use `typeorm migration:generate` and `typeorm migration:run`.

## Zero-Downtime Migration Strategies

### Adding a Column
1. Add the column as nullable (or with a default value) -- no app change needed.
2. Deploy new app code that writes to the new column.
3. Backfill existing rows if needed.
4. Add NOT NULL constraint only after all rows are populated.

### Removing a Column
1. Deploy app code that no longer reads or writes the column.
2. Wait for all old application instances to drain.
3. Drop the column in a subsequent migration.

### Renaming a Column
Do not rename directly. Instead:
1. Add the new column.
2. Deploy code that writes to both old and new columns.
3. Backfill the new column from the old.
4. Deploy code that reads only from the new column.
5. Drop the old column.

### Adding an Index
- Use `CREATE INDEX CONCURRENTLY` (PostgreSQL) to avoid locking the table.
- In MySQL, use `ALTER TABLE ... ADD INDEX` with `ALGORITHM=INPLACE, LOCK=NONE` where supported.

## Rollback Planning

- **Every migration must have a rollback (down) function**: If the framework supports it, always write the reverse operation.
- **Test rollbacks explicitly**: Run `migrate down` in your CI/CD pipeline to verify rollbacks work.
- **Data-destructive operations need extra care**: Dropping columns or tables cannot be trivially rolled back. Consider keeping the column for a grace period before dropping.
- **Keep a rollback runbook**: Document the exact commands to revert each migration, including any data restoration steps.

## Schema Migration vs. Data Migration

| Aspect | Schema Migration | Data Migration |
|--------|-----------------|----------------|
| Purpose | Change table structure (columns, indexes, constraints) | Transform or move data between columns/tables |
| Speed | Usually fast (DDL operations) | Can be slow on large tables |
| Risk | Locking, constraint violations | Data loss, corruption, timeouts |
| Strategy | Run in transactions where supported | Batch process in chunks to avoid long locks |

### Data Migration Best Practices
- Process in batches (e.g., 1000 rows at a time) to avoid locking the entire table.
- Make data migrations idempotent so they can be safely re-run.
- Log progress so you can monitor and resume if interrupted.
- Validate data after migration: row counts, checksums, spot checks.

## Pre-Migration Checklist

- [ ] Migration has been reviewed by another developer.
- [ ] Both `up` and `down` functions are implemented and tested.
- [ ] Migration has been tested against a staging copy of production data.
- [ ] Backup of the production database has been taken.
- [ ] Application code is backwards compatible with both old and new schemas.
- [ ] Estimated migration time is acceptable for the maintenance window (if any).
- [ ] Monitoring and alerting are in place to detect issues post-migration.
