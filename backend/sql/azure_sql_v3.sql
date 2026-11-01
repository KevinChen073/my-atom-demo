-- Match Linux artifact paths: SQL Server's default CI collation merges App.css and app.css.
-- Run explicitly with the migration role, never from the application identity.
IF OBJECT_ID(N'dbo.version_files', N'U') IS NULL
    THROW 50001, 'version_files is missing; apply schema v2 first', 1;
GO
IF (SELECT collation_name FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.version_files') AND name = N'relative_path')
    <> N'Latin1_General_100_BIN2'
BEGIN
    BEGIN TRY
        BEGIN TRANSACTION;
        ALTER TABLE dbo.version_files DROP CONSTRAINT pk_version_files;
        ALTER TABLE dbo.version_files ALTER COLUMN relative_path
            NVARCHAR(400) COLLATE Latin1_General_100_BIN2 NOT NULL;
        ALTER TABLE dbo.version_files ADD CONSTRAINT pk_version_files
            PRIMARY KEY (version_id, relative_path);
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
GO
IF (SELECT collation_name FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.version_files') AND name = N'relative_path')
    <> N'Latin1_General_100_BIN2'
    THROW 50002, 'version_files.relative_path must use BIN2 collation', 1;
IF NOT EXISTS (SELECT 1 FROM dbo.myatom_schema_version WHERE version = 3)
    INSERT INTO dbo.myatom_schema_version(version) VALUES (3);
