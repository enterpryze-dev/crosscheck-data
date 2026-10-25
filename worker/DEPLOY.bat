@echo off
rem Deploys the Crosscheck live relay to Cloudflare with your existing wrangler login.
cd /d "%~dp0"
set CI=1
call npx --yes wrangler@4 deploy > deploy-log.txt 2>&1
echo exit %errorlevel% >> deploy-log.txt
