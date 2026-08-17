# Conteúdo a colar no arquivo WSGI gerado pelo PythonAnywhere
# (aba "Web" > link do arquivo "WSGI configuration file").
# Apague o conteúdo de exemplo que já estiver lá e cole isto no lugar,
# ajustando "SEU_USUARIO" para o seu nome de usuário do PythonAnywhere.

import sys
import os

project_home = '/home/SEU_USUARIO/recibos-aluguel'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Variáveis de ambiente (ajuste os valores conforme desejar)
os.environ['SECRET_KEY'] = 'troque-por-um-valor-aleatorio-e-secreto'
os.environ['ADMIN_EMAIL'] = 'admin@exemplo.com'
os.environ['ADMIN_PASSWORD'] = 'mudeEstaSenha123'

from app import app as application
