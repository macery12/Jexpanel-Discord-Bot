# Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for automatic database migrations.

## How It Works

When the bot starts, it automatically runs any pending database migrations to ensure your database schema is up-to-date with the code. You don't need to do anything manually!

## For Developers: Creating New Migrations

When you make changes to the database models in `bot/db/models.py`, you need to create a migration:

### 1. Automatic Migration Generation (Recommended)

```bash
# Make sure dependencies are installed
pip install -r requirements.txt

# Generate migration automatically by comparing models to database
alembic revision --autogenerate -m "Description of your changes"
```

This will create a new migration file in `alembic/versions/` with the changes detected.

### 2. Manual Migration Creation

If you prefer to write migrations manually:

```bash
alembic revision -m "Description of your changes"
```

Then edit the generated file in `alembic/versions/` to add your upgrade and downgrade logic.

### 3. Alternative: Use the Helper Script

```bash
python -m bot.db.migrations "Description of your changes"
```

## Migration File Structure

Each migration file has:
- `revision`: Unique ID for this migration
- `down_revision`: ID of the previous migration
- `upgrade()`: Function that applies the migration
- `downgrade()`: Function that reverses the migration

Example:
```python
def upgrade() -> None:
    op.add_column('server_alias', sa.Column('new_field', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('server_alias', 'new_field')
```

## Testing Migrations Locally

```bash
# Check current migration status
alembic current

# Show all migrations
alembic history

# Upgrade to latest
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>
```

## Important Notes

1. **Automatic on Startup**: Migrations run automatically when the bot starts
2. **No Manual SQL**: Never modify the database schema manually - always use migrations
3. **Test Before Deploy**: Test migrations on a copy of your database first
4. **Reversible**: Always write proper `downgrade()` functions for rollback capability
5. **Version Control**: Always commit migration files to git

## Current Migrations

- `001_user_aliases`: Add user-specific alias support with `discord_user_id` and `created_at` fields

## Troubleshooting

### Migration conflicts
If you get migration conflicts, you may need to:
1. Merge the conflicting migration branches
2. Or delete your local database and let migrations rebuild it from scratch

### Database out of sync
If your database schema doesn't match the models:
```bash
# Generate a new migration to fix it
alembic revision --autogenerate -m "Sync database schema"
```

### Need to start fresh
For development, you can delete the database and let it rebuild:
```bash
rm bot.db  # or your database file
# Restart the bot - it will run all migrations from scratch
```
