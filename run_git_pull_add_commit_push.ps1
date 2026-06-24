echo "`npy_youtube-transcript-api専用です`n"
echo "`ncd ~\py_youtube-transcript-api`n"
cd ~\py_youtube-transcript-api
echo "`n.venv/scripts/activate`n"
.venv/scripts/activate
echo "`npython build_html_site.py`n"
python build_html_site.py


echo "`ngit pull`n"
git pull
echo "`ngit add commit push`n"
git add .
git commit -m "git pull add commit push $(Get-Date -Format 'yyyyMMdd HH:mm')"
git push -u origin main


