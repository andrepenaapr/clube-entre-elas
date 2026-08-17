# Sistema de Recibos de Aluguel

Sistema web simples para cadastrar imóveis, clientes (inquilinos) e contratos
de locação, e emitir recibos de aluguel e de caução em PDF, com histórico
completo. Foi pensado para ser hospedado na nuvem: você e as pessoas que
você autorizar acessam de qualquer lugar, por navegador, sem precisar
instalar nada em nenhum computador.

## O que o sistema faz

- Cadastro de imóveis (endereço, apelido, valor padrão do aluguel).
- Cadastro de clientes/inquilinos (nome, CPF/CNPJ, telefone, e-mail).
- Cadastro de contratos vinculando imóvel + um ou mais clientes (ex.: casal
  como co-locatários), com valor do aluguel, periodicidade padrão (mês
  fechado, últimos 30 dias ou próximos 30 dias) e informações de caução (se
  existe, valor, status "a depositar"/"depositado" e data do depósito).
- Emissão de recibos em PDF no formato de recibo tradicional em texto
  corrido ("Pelo presente instrumento, eu [locador]... declaro que recebi
  ... de [locatário(s)]..."), com valor por extenso, período de referência,
  data por extenso e linha para assinatura — mesmo padrão de texto usado
  nos seus recibos atuais.
- Histórico de todos os recibos emitidos, sempre disponível para reabrir e
  baixar novamente.
- Login com usuários e dois papéis: administrador (acesso total, inclusive
  gestão de usuários e configurações) e operador (cadastra imóveis,
  clientes, contratos e emite recibos).

## Como está organizado

```
recibos-aluguel/
├── app.py                # aplicação Flask (rotas)
├── models.py              # modelos de dados (banco)
├── pdf.py                 # geração do PDF do recibo
├── periods.py              # cálculo das datas de cada periodicidade
├── templates/              # páginas HTML
├── requirements.txt        # dependências Python
├── Procfile / render.yaml  # configuração para hospedar no Render.com
├── wsgi_pythonanywhere_snippet.py  # configuração para hospedar no PythonAnywhere
└── .env.example             # exemplo de variáveis de ambiente
```

## Colocando no ar (hospedagem na nuvem)

Caminho único, escolhido por ser o mais simples tanto para configurar
quanto para atualizar depois: **GitHub + Render + Supabase**. Atualizar o
sistema no futuro é sempre a mesma ação simples: editar o arquivo no
GitHub (ou enviar uma nova versão) → o Render publica a mudança sozinho,
em 1 a 2 minutos, sem nenhum passo manual adicional.

1. **Supabase (banco de dados)** — crie um projeto gratuito em
   https://supabase.com. Em *Project Settings → Database*, copie a
   "Connection string" no formato URI (o modo *Session pooler* funciona
   bem para este tipo de app). Ela se parece com
   `postgresql://postgres.xxxx:SENHA@aws-0-regiao.pooler.supabase.com:5432/postgres`.
2. **GitHub (código)** — crie um repositório (pode ser privado) e envie os
   arquivos deste projeto pelo botão **Add file → Upload files**, direto
   no navegador, sem precisar de linha de comando.
3. **Render (executa o sistema)** — crie uma conta gratuita em
   https://render.com, clique em **New → Web Service**, conecte ao GitHub
   e escolha o repositório que você acabou de criar.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Em **Environment Variables**, adicione:
     - `SECRET_KEY` — qualquer texto longo e aleatório
     - `ADMIN_EMAIL` — seu e-mail de administrador
     - `ADMIN_PASSWORD` — senha inicial do administrador
     - `DATABASE_URL` — a connection string copiada do Supabase
   - Marque a opção **Auto-Deploy** como ativada (geralmente já vem assim
     por padrão) — é isso que garante que qualquer atualização enviada ao
     GitHub publique automaticamente.
   - Clique em **Create Web Service**. Em poucos minutos o Render entrega
     uma URL pública (ex.: `https://recibos-aluguel.onrender.com`) — o
     sistema já está no ar.

O `requirements.txt` já inclui o driver do Postgres (`psycopg2-binary`) e o
`app.py` já lê a variável `DATABASE_URL` automaticamente — não é preciso
alterar nenhum código, só configurar as variáveis de ambiente acima.

Nenhuma dessas plataformas é obrigatória em si — são só a combinação mais
prática para quem já tem conta nelas. Cloudflare (domínio próprio) e
PythonAnywhere (tudo em uma conta só, mas com atualização manual em vez de
automática) continuam sendo alternativas válidas, só não são o caminho
recomendado aqui porque o objetivo era simplicidade tanto para configurar
quanto para atualizar.

## Primeiro acesso

Ao subir o sistema pela primeira vez, ele cria automaticamente um usuário
administrador com o e-mail e a senha definidos nas variáveis de ambiente
(`ADMIN_EMAIL` / `ADMIN_PASSWORD`). Faça login com esses dados e:

1. Vá em **Configurações** e preencha seus dados como locador (nome,
   CPF/CNPJ, endereço) — eles aparecem nos recibos emitidos.
2. Vá em **Usuários** e crie um acesso para cada outra pessoa que vai usar
   o sistema, escolhendo o papel adequado (administrador ou operador).
3. Cadastre seus imóveis, seus clientes e os contratos de locação.
4. Dentro de cada contrato, use o botão **Emitir recibo** sempre que
   receber um pagamento.

## Rodando localmente (opcional, para testar antes de publicar)

```
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # edite os valores se quiser
python app.py
```

Depois acesse http://localhost:5000 no navegador. O banco de dados local é
criado automaticamente em `instance/recibos.db`.

## Segurança

- Troque a senha do administrador padrão assim que possível (aba
  **Usuários** → editar o seu usuário → definir nova senha).
- Sempre acesse o sistema por um endereço `https://` (o Render e o
  PythonAnywhere já fornecem isso automaticamente).
- Use `SECRET_KEY` diferente do valor de exemplo em qualquer ambiente que
  não seja apenas para testes locais.
