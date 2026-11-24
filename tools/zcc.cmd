@echo off
rem Host C compiler wrapper: zig cc from the project venv (no MSVC/MinGW install needed).
"%~dp0..\.venv\Lib\site-packages\ziglang\zig.exe" cc %*
