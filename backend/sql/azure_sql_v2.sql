-- Immutable UTF-8 version snapshots. Existing v1 versions must be imported first.
IF OBJECT_ID(N'dbo.version_files', N'U') IS NULL
    CREATE TABLE dbo.version_files (
        version_id VARCHAR(36) NOT NULL,
        relative_path NVARCHAR(400) NOT NULL,
        text_content NVARCHAR(MAX) NOT NULL,
        utf8_bytes INT NOT NULL,
        sha256 CHAR(64) NOT NULL,
        kind VARCHAR(10) NOT NULL,
        mime_type VARCHAR(100) NOT NULL,
        CONSTRAINT pk_version_files PRIMARY KEY (version_id, relative_path),
        CONSTRAINT fk_version_files_version FOREIGN KEY (version_id)
            REFERENCES dbo.versions(id) ON DELETE CASCADE,
        CONSTRAINT ck_version_files_size CHECK (utf8_bytes >= 0 AND utf8_bytes <= 524288),
        CONSTRAINT ck_version_files_kind CHECK (kind IN ('source', 'dist'))
    );
GO
IF NOT EXISTS (SELECT 1 FROM dbo.myatom_schema_version WHERE version=2)
    INSERT INTO dbo.myatom_schema_version(version) VALUES (2);
