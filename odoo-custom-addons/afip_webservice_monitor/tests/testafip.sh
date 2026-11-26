if curl -s --max-time 5 https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL | grep -qi definitions; then
    echo "AFIP WSFE OK"
else
    echo "AFIP WSFE CAÍDO"
fi
