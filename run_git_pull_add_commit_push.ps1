echo "`npy_youtube-transcript-api専用です"
echo "`ncd ~\py_youtube-transcript-api"
cd ~\py_youtube-transcript-api
echo "`n.venv/scripts/activate"
.venv/scripts/activate
echo "`npython build_html_site.py"
python build_html_site.py


echo "`n---------------------------------`ngit pull`n---------------------------------`n"
git pull
echo "`ngit add commit push`n"
git add .
git commit -m "git pull add commit push $(Get-Date -Format 'yyyyMMdd HH:mm')"
git push -u origin main


