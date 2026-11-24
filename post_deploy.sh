# 1. Delete the conflicting pyOpenSSL (note the path in your traceback is /usr/local/lib/python3.9/dist-packages/)
rm -rf /usr/local/lib/python3.9/dist-packages/OpenSSL
rm -rf /usr/local/lib/python3.9/dist-packages/pyOpenSSL-*.dist-info

python3 -m pip install pyOpenSSL==21.0.0 cryptography==3.4.8

#pip install git+https://github.com/filoquin/pyafipws.git@py3k
pip install PyAfipWs@git+https://github.com/reingart/pyafipws@545ddcee9d1c59772ba8d418c28d8a6407a686e1
pip install aeroolib@git+https://github.com/adhoc-dev/aeroolib@eb3f232f250ce6da978c41e47fdb95b43b0dad8d

pip install  currency2text@git+https://github.com/aeroo/currency2text.git@e666e17eb54f5a49f5cfb3825d8513a4d1510249

chmod 777 /usr/local/lib/python3.9/dist-packages/pyafipws

/etc/init.d/odoo restart


