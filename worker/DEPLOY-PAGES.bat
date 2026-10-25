@echo off
rem Deploys the Crosscheck live relay as a Pages project (neutral pages.dev address).
cd /d "%~dp0"
set CI=1
call npx --yes wrangler@4 pages project create crosscheck-live --production-branch main > deploy-pages-log.txt 2>&1
call npx --yes wrangler@4 pages deploy pages --project-name crosscheck-live --branch main --commit-dirty=true >> deploy-pages-log.txt 2>&1
echo exit %errorlevel% >> deploy-pages-log.txt
