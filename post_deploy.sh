echo "
deb http://snapshot.debian.org/archive/debian/20250908T000000Z bullseye main
#deb http://deb.debian.org/debian bullseye main
deb http://snapshot.debian.org/archive/debian-security/20250908T000000Z bullseye-security main
#deb http://deb.debian.org/debian-security bullseye-security main
deb http://snapshot.debian.org/archive/debian/20250908T000000Z bullseye-updates main
#deb http://deb.debian.org/debian bullseye-updates main
" >  /etc/apt/sources.list
apt update 
apt install git python3-pykcs11
python3 -m pip install pyOpenSSL==21.0.0 cryptography==3.4.8

pip install currency2text@git+https://github.com/aeroo/currency2text.git@e666e17eb54f5a49f5cfb3825d8513a4d1510249
pip install PyAfipWs@git+https://github.com/reingart/pyafipws@545ddcee9d1c59772ba8d418c28d8a6407a686e1
pip install aeroolib@git+https://github.com/adhoc-dev/aeroolib@eb3f232f250ce6da978c41e47fdb95b43b0dad8d

chmod 777 /usr/local/lib/python3.9/dist-packages/pyafipws
