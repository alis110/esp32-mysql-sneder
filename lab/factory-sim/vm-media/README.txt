AlisBoard lab DVD — copy/restore inside the Windows 7 VM

1. Install SQL Server (32-bit) with instance name: WINCC
   Windows Authentication. User Operator, password 123.

2. Open cmd as Administrator and run:
   D:\RESTORE.bat
   (DVD letter may be E: — then E:\RESTORE.bat)

3. Then:
   sqlcmd -S .\WINCC -E -i D:\seed-uncompressed.sql

4. Copy AlisBoard.exe from the USB/ESP disk and Test SQL:
   Server  CPUPC01\WINCC   or   .\WINCC
   Database auto
