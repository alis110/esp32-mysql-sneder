-- Lab-only: WinCC dump stores flow in TagCompressed (unreadable).
-- Seed TagUncompressed so AlisBoard.exe can SELECT like the factory query.
USE [CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202808081515];
SET NOCOUNT ON;

IF NOT EXISTS (SELECT 1 FROM Archive)
BEGIN
    RAISERROR('Archive table is empty — bak restore failed', 16, 1);
    RETURN;
END

DELETE FROM TagUncompressed;

DECLARE @base datetime = DATEADD(minute, -30, GETDATE());
DECLARE @i int = 0;
WHILE @i < 40
BEGIN
    INSERT INTO TagUncompressed (ValueID, TimeStamp, MS, RealValue, Quality, Flags)
    SELECT
        a.ValueID,
        DATEADD(second, @i * 11 + CAST(a.ValueID AS int), @base),
        CAST(a.ValueID AS smallint),
        CASE a.ValueID
            WHEN 1 THEN 12.4 + (@i % 7) * 0.31
            WHEN 2 THEN 8.1 + (@i % 5) * 0.22
            WHEN 4 THEN 6.7 + (@i % 6) * 0.18
            WHEN 5 THEN 5.2 + (@i % 4) * 0.15
            WHEN 6 THEN 4.8 + (@i % 8) * 0.11
            WHEN 7 THEN 11.9 + (@i % 6) * 0.27
            WHEN 8 THEN 3.3 + (@i % 5) * 0.09
            WHEN 9 THEN 2.8 + (@i % 4) * 0.12
            WHEN 10 THEN 2.1 + (@i % 7) * 0.08
            WHEN 11 THEN 1.6 + (@i % 3) * 0.14
            WHEN 12 THEN 9.5 + (@i % 9) * 0.19
            ELSE 1.0
        END,
        128,
        0
    FROM Archive a;
    SET @i = @i + 1;
END

SELECT COUNT(*) AS uncompressed_rows FROM TagUncompressed;
SELECT TOP 3
    CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000 + u.MS AS id,
    u.ValueID,
    RTRIM(a.ValueName) AS TagName,
    u.RealValue
FROM TagUncompressed u
LEFT JOIN Archive a ON a.ValueID = u.ValueID
ORDER BY u.TimeStamp, u.MS, u.ValueID;
