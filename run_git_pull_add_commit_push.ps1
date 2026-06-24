echo "`npy_youtube-transcript-api ---------------`n"

cd ~\py_youtube-transcript-api
echo "`ngit pull`n"
git pull
echo "`ngit add commit push`n"
git add .
git commit -m "git pull add commit push $(Get-Date -Format 'yyyyMMdd HH:mm')"
git push -u origin main


