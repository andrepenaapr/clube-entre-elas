import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request, flash, abort,
    send_file, session
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
import io

from models import (
    db, User, Client, Property, Rental, Receipt, Settings,
    ROLE_ADMIN, ROLE_OPERADOR,
    PERIODICIDADE_LABELS, PERIODICIDADE_MES_FECHADO, PERIODICIDADE_MES_VENCIDO,
    PERIODICIDADE_MES_VINCENDO,
    STATUS_CAUCAO_LABELS, STATUS_CAUCAO_A_DEPOSITAR, STATUS_CAUCAO_DEPOSITADO,
    TIPO_RECIBO_LABELS, TIPO_RECIBO_ALUGUEL, TIPO_RECIBO_CAUCAO,
    TIPO_RECIBO_IPTU, TIPO_RECIBO_OUTROS,
)
from periods import first_period, next_period, MESES_PT
from pdf import generate_receipt_pdf, build_tenants_text

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-troque-esta-chave")

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # compat com URLs antigas do Render/Heroku (postgres:// -> postgresql://)
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    else:
        instance_dir = os.path.join(BASE_DIR, "instance")
        os.makedirs(instance_dir, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(instance_dir, "recibos.db")

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    csrf = CSRFProtect(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Faça login para continuar."

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_admin:
                abort(403)
            return f(*args, **kwargs)
        return wrapper

    @app.context_processor
    def inject_globals():
        return {
            "PERIODICIDADE_LABELS": PERIODICIDADE_LABELS,
            "STATUS_CAUCAO_LABELS": STATUS_CAUCAO_LABELS,
            "TIPO_RECIBO_LABELS": TIPO_RECIBO_LABELS,
            "current_year": date.today().year,
        }

    # ---------- helpers ----------
    def parse_decimal(value, default=None):
        if value is None or value == "":
            return default
        value = value.replace(".", "").replace(",", ".") if "," in value else value
        try:
            return Decimal(value)
        except InvalidOperation:
            return default

    def parse_date(value, default=None):
        if not value:
            return default
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return default

    def next_receipt_number():
        settings = Settings.get()
        year = date.today().year
        number = f"{settings.next_receipt_seq:04d}/{year}"
        settings.next_receipt_seq += 1
        db.session.add(settings)
        return number

    def compute_next_rental_period(rental, issue_date):
        """O sistema decide o período de referência sozinho: continua de onde
        parou o último recibo de aluguel deste contrato, ou calcula o
        primeiro período com base na periodicidade/vencimento configurados."""
        last_receipt = (
            Receipt.query.filter_by(rental_id=rental.id, tipo=TIPO_RECIBO_ALUGUEL)
            .filter(Receipt.period_end.isnot(None))
            .order_by(Receipt.period_end.desc())
            .first()
        )
        if last_receipt and last_receipt.period_end:
            return next_period(last_receipt.period_end)
        return first_period(rental.default_periodicity, issue_date, due_day=rental.due_day)

    # ---------- auth ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()
            if user and user.active and user.check_password(password):
                login_user(user)
                flash("Login realizado com sucesso.", "success")
                next_url = request.args.get("next")
                return redirect(next_url or url_for("dashboard"))
            flash("E-mail ou senha inválidos.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Você saiu do sistema.", "info")
        return redirect(url_for("login"))

    # ---------- dashboard ----------
    @app.route("/")
    @login_required
    def dashboard():
        total_properties = Property.query.filter_by(active=True).count()
        total_clients = Client.query.filter_by(active=True).count()
        total_rentals = Rental.query.filter_by(active=True).count()
        pending_deposits = Rental.query.filter_by(
            has_deposit=True, deposit_status=STATUS_CAUCAO_A_DEPOSITAR, active=True
        ).count()
        recent_receipts = Receipt.query.order_by(Receipt.id.desc()).limit(8).all()

        today = date.today()
        warning_limit = today + timedelta(days=30)
        adjustments_due = (
            Rental.query.filter(
                Rental.active == True,  # noqa: E712
                Rental.adjustment_date.isnot(None),
                Rental.adjustment_date <= warning_limit,
            ).order_by(Rental.adjustment_date).all()
        )
        endings_due = (
            Rental.query.filter(
                Rental.active == True,  # noqa: E712
                Rental.end_date.isnot(None),
                Rental.end_date <= warning_limit,
            ).order_by(Rental.end_date).all()
        )

        return render_template(
            "dashboard.html",
            total_properties=total_properties,
            total_clients=total_clients,
            total_rentals=total_rentals,
            pending_deposits=pending_deposits,
            recent_receipts=recent_receipts,
            adjustments_due=adjustments_due,
            endings_due=endings_due,
            today=today,
        )

    # ---------- clients ----------
    @app.route("/clientes")
    @login_required
    def clients_list():
        clients = Client.query.order_by(Client.name).all()
        return render_template("clients_list.html", clients=clients)

    @app.route("/clientes/novo", methods=["GET", "POST"])
    @login_required
    @admin_required
    def client_new():
        if request.method == "POST":
            c = Client(
                name=request.form.get("name", "").strip(),
                document=request.form.get("document", "").strip(),
                phone=request.form.get("phone", "").strip(),
                email=request.form.get("email", "").strip(),
                address=request.form.get("address", "").strip(),
                notes=request.form.get("notes", "").strip(),
            )
            if not c.name:
                flash("Informe o nome do cliente.", "danger")
                return render_template("client_form.html", client=None, form=request.form)
            db.session.add(c)
            db.session.commit()
            flash("Cliente cadastrado com sucesso.", "success")
            return redirect(url_for("clients_list"))
        return render_template("client_form.html", client=None, form=None)

    @app.route("/clientes/<int:client_id>/editar", methods=["GET", "POST"])
    @login_required
    @admin_required
    def client_edit(client_id):
        c = Client.query.get_or_404(client_id)
        if request.method == "POST":
            c.name = request.form.get("name", "").strip()
            c.document = request.form.get("document", "").strip()
            c.phone = request.form.get("phone", "").strip()
            c.email = request.form.get("email", "").strip()
            c.address = request.form.get("address", "").strip()
            c.notes = request.form.get("notes", "").strip()
            c.active = request.form.get("active") == "on"
            if not c.name:
                flash("Informe o nome do cliente.", "danger")
                return render_template("client_form.html", client=c, form=None)
            db.session.commit()
            flash("Cliente atualizado.", "success")
            return redirect(url_for("clients_list"))
        return render_template("client_form.html", client=c, form=None)

    # ---------- properties ----------
    @app.route("/imoveis")
    @login_required
    def properties_list():
        properties = Property.query.order_by(Property.nickname).all()
        return render_template("properties_list.html", properties=properties)

    @app.route("/imoveis/novo", methods=["GET", "POST"])
    @login_required
    @admin_required
    def property_new():
        if request.method == "POST":
            p = Property(
                nickname=request.form.get("nickname", "").strip(),
                address=request.form.get("address", "").strip(),
                description=request.form.get("description", "").strip(),
                default_rent_value=parse_decimal(request.form.get("default_rent_value")),
            )
            if not p.nickname or not p.address:
                flash("Informe ao menos o apelido e o endereço do imóvel.", "danger")
                return render_template("property_form.html", property=None)
            db.session.add(p)
            db.session.commit()
            flash("Imóvel cadastrado com sucesso.", "success")
            return redirect(url_for("properties_list"))
        return render_template("property_form.html", property=None)

    @app.route("/imoveis/<int:property_id>/editar", methods=["GET", "POST"])
    @login_required
    @admin_required
    def property_edit(property_id):
        p = Property.query.get_or_404(property_id)
        if request.method == "POST":
            p.nickname = request.form.get("nickname", "").strip()
            p.address = request.form.get("address", "").strip()
            p.description = request.form.get("description", "").strip()
            p.default_rent_value = parse_decimal(request.form.get("default_rent_value"))
            p.active = request.form.get("active") == "on"
            if not p.nickname or not p.address:
                flash("Informe ao menos o apelido e o endereço do imóvel.", "danger")
                return render_template("property_form.html", property=p)
            db.session.commit()
            flash("Imóvel atualizado.", "success")
            return redirect(url_for("properties_list"))
        return render_template("property_form.html", property=p)

    # ---------- rentals (contratos) ----------
    @app.route("/contratos")
    @login_required
    def rentals_list():
        rentals = Rental.query.order_by(Rental.id.desc()).all()
        return render_template("rentals_list.html", rentals=rentals)

    @app.route("/contratos/novo", methods=["GET", "POST"])
    @login_required
    @admin_required
    def rental_new():
        properties = Property.query.filter_by(active=True).order_by(Property.nickname).all()
        clients = Client.query.filter_by(active=True).order_by(Client.name).all()
        if request.method == "POST":
            has_deposit = request.form.get("has_deposit") == "on"
            client_ids = request.form.getlist("client_ids", type=int)
            r = Rental(
                property_id=request.form.get("property_id", type=int),
                rent_value=parse_decimal(request.form.get("rent_value")),
                default_periodicity=request.form.get("default_periodicity", PERIODICIDADE_MES_FECHADO),
                due_day=request.form.get("due_day", type=int),
                has_deposit=has_deposit,
                deposit_value=parse_decimal(request.form.get("deposit_value")) if has_deposit else None,
                deposit_status=request.form.get("deposit_status") if has_deposit else None,
                deposit_date=parse_date(request.form.get("deposit_date")) if has_deposit else None,
                deposit_notes=request.form.get("deposit_notes", "").strip(),
                start_date=parse_date(request.form.get("start_date")),
                end_date=parse_date(request.form.get("end_date")),
                adjustment_date=parse_date(request.form.get("adjustment_date")),
                notes=request.form.get("notes", "").strip(),
            )
            if not r.property_id or not client_ids or r.rent_value is None:
                flash("Selecione o imóvel, ao menos um cliente e informe o valor do aluguel.", "danger")
                return render_template("rental_form.html", rental=None, properties=properties, clients=clients)
            if r.default_periodicity in (PERIODICIDADE_MES_VENCIDO, PERIODICIDADE_MES_VINCENDO) and not r.due_day:
                flash("Informe o dia de vencimento do aluguel para usar mês vencido ou vincendo.", "danger")
                return render_template("rental_form.html", rental=None, properties=properties, clients=clients)
            r.clients = Client.query.filter(Client.id.in_(client_ids)).all()
            db.session.add(r)
            db.session.commit()
            flash("Contrato cadastrado com sucesso.", "success")
            return redirect(url_for("rentals_list"))
        return render_template("rental_form.html", rental=None, properties=properties, clients=clients)

    @app.route("/contratos/<int:rental_id>/editar", methods=["GET", "POST"])
    @login_required
    @admin_required
    def rental_edit(rental_id):
        r = Rental.query.get_or_404(rental_id)
        properties = Property.query.filter_by(active=True).order_by(Property.nickname).all()
        clients = Client.query.filter_by(active=True).order_by(Client.name).all()
        if request.method == "POST":
            has_deposit = request.form.get("has_deposit") == "on"
            client_ids = request.form.getlist("client_ids", type=int)
            r.property_id = request.form.get("property_id", type=int)
            r.rent_value = parse_decimal(request.form.get("rent_value"))
            r.default_periodicity = request.form.get("default_periodicity", PERIODICIDADE_MES_FECHADO)
            r.due_day = request.form.get("due_day", type=int)
            r.has_deposit = has_deposit
            r.deposit_value = parse_decimal(request.form.get("deposit_value")) if has_deposit else None
            r.deposit_status = request.form.get("deposit_status") if has_deposit else None
            r.deposit_date = parse_date(request.form.get("deposit_date")) if has_deposit else None
            r.deposit_notes = request.form.get("deposit_notes", "").strip()
            r.start_date = parse_date(request.form.get("start_date"))
            r.end_date = parse_date(request.form.get("end_date"))
            r.adjustment_date = parse_date(request.form.get("adjustment_date"))
            r.notes = request.form.get("notes", "").strip()
            r.active = request.form.get("active") == "on"
            if not r.property_id or not client_ids or r.rent_value is None:
                flash("Selecione o imóvel, ao menos um cliente e informe o valor do aluguel.", "danger")
                return render_template("rental_form.html", rental=r, properties=properties, clients=clients)
            if r.default_periodicity in (PERIODICIDADE_MES_VENCIDO, PERIODICIDADE_MES_VINCENDO) and not r.due_day:
                flash("Informe o dia de vencimento do aluguel para usar mês vencido ou vincendo.", "danger")
                return render_template("rental_form.html", rental=r, properties=properties, clients=clients)
            r.clients = Client.query.filter(Client.id.in_(client_ids)).all()
            db.session.commit()
            flash("Contrato atualizado.", "success")
            return redirect(url_for("rentals_list"))
        return render_template("rental_form.html", rental=r, properties=properties, clients=clients)

    @app.route("/contratos/<int:rental_id>")
    @login_required
    def rental_detail(rental_id):
        r = Rental.query.get_or_404(rental_id)
        return render_template("rental_detail.html", rental=r, today=date.today())

    # ---------- receipts (recibos) ----------
    @app.route("/recibos/novo", methods=["GET", "POST"])
    @login_required
    def receipt_pick_rental():
        if request.method == "POST":
            rental_id = request.form.get("rental_id", type=int)
            if not rental_id:
                flash("Selecione um contrato.", "danger")
                return redirect(url_for("receipt_pick_rental"))
            return redirect(url_for("receipt_new", rental_id=rental_id))
        rentals = (
            Rental.query.filter_by(active=True)
            .join(Property)
            .order_by(Property.nickname)
            .all()
        )
        return render_template("receipt_pick_rental.html", rentals=rentals)

    @app.route("/contratos/<int:rental_id>/recibos/novo", methods=["GET", "POST"])
    @login_required
    def receipt_new(rental_id):
        r = Rental.query.get_or_404(rental_id)
        settings = Settings.get()
        today = date.today()
        tipos_disponiveis = [TIPO_RECIBO_ALUGUEL]
        if r.has_deposit:
            tipos_disponiveis.append(TIPO_RECIBO_CAUCAO)
        tipos_disponiveis += [TIPO_RECIBO_IPTU, TIPO_RECIBO_OUTROS]

        if request.method == "POST":
            tipo = request.form.get("tipo", TIPO_RECIBO_ALUGUEL)
            if tipo not in tipos_disponiveis:
                tipo = TIPO_RECIBO_ALUGUEL
            issue_date = parse_date(request.form.get("issue_date"), default=today)
            notes = request.form.get("notes", "").strip()

            if tipo == TIPO_RECIBO_ALUGUEL:
                value = parse_decimal(request.form.get("value"), default=r.rent_value)
                periodicity = r.default_periodicity
                period_start, period_end = compute_next_rental_period(r, issue_date)
            elif tipo == TIPO_RECIBO_CAUCAO:
                value = parse_decimal(request.form.get("value"), default=r.deposit_value)
                periodicity, period_start, period_end = None, None, None
            else:
                value = parse_decimal(request.form.get("value"))
                periodicity, period_start, period_end = None, None, None
                if tipo == TIPO_RECIBO_OUTROS and not notes:
                    flash("Para o tipo 'Outros', descreva do que se trata nas observações.", "danger")
                    return redirect(url_for("receipt_new", rental_id=r.id))

            if value is None:
                flash("Informe o valor do recibo.", "danger")
                return redirect(url_for("receipt_new", rental_id=r.id))

            receipt = Receipt(
                number=next_receipt_number(),
                rental_id=r.id,
                issued_by_id=current_user.id,
                tipo=tipo,
                value=value,
                periodicity=periodicity,
                period_start=period_start,
                period_end=period_end,
                issue_date=issue_date,
                notes=notes,
                snapshot_property_nickname=r.property.nickname,
                snapshot_property_address=r.property.address,
                snapshot_clients_names=r.clients_names,
                snapshot_clients_text=build_tenants_text(r.clients),
                snapshot_landlord_name=settings.landlord_name,
                snapshot_landlord_document=settings.landlord_document,
                snapshot_landlord_address=settings.landlord_address,
                snapshot_landlord_city=settings.landlord_city,
            )
            db.session.add(receipt)

            # se for recibo de caução, marcar automaticamente como depositado
            if tipo == TIPO_RECIBO_CAUCAO and r.has_deposit:
                r.deposit_status = STATUS_CAUCAO_DEPOSITADO
                r.deposit_date = issue_date
                db.session.add(r)

            db.session.commit()
            flash(f"Recibo {receipt.number} emitido com sucesso.", "success")
            return redirect(url_for("receipt_detail", receipt_id=receipt.id))

        # GET: o próprio sistema já calcula o período de aluguel sugerido
        preview_start, preview_end = compute_next_rental_period(r, today)
        return render_template(
            "receipt_form.html",
            rental=r,
            today=today,
            preview_start=preview_start,
            preview_end=preview_end,
            settings=settings,
            tipos_disponiveis=tipos_disponiveis,
        )

    @app.route("/recibos")
    @login_required
    def receipts_list():
        receipts = Receipt.query.order_by(Receipt.id.desc()).all()
        return render_template("receipts_list.html", receipts=receipts)

    @app.route("/recibos/<int:receipt_id>")
    @login_required
    def receipt_detail(receipt_id):
        receipt = Receipt.query.get_or_404(receipt_id)
        return render_template("receipt_detail.html", receipt=receipt)

    @app.route("/recibos/<int:receipt_id>/pdf")
    @login_required
    def receipt_pdf(receipt_id):
        receipt = Receipt.query.get_or_404(receipt_id)
        pdf_bytes = generate_receipt_pdf(receipt)
        filename = f"recibo_{receipt.number.replace('/', '-')}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=filename,
        )

    # ---------- settings (locador) ----------
    @app.route("/configuracoes", methods=["GET", "POST"])
    @login_required
    @admin_required
    def settings_view():
        settings = Settings.get()
        if request.method == "POST":
            settings.landlord_name = request.form.get("landlord_name", "").strip()
            settings.landlord_document = request.form.get("landlord_document", "").strip()
            settings.landlord_address = request.form.get("landlord_address", "").strip()
            settings.landlord_city = request.form.get("landlord_city", "").strip()
            settings.landlord_phone = request.form.get("landlord_phone", "").strip()
            settings.landlord_email = request.form.get("landlord_email", "").strip()
            settings.receipt_footer_text = request.form.get("receipt_footer_text", "").strip()
            db.session.commit()
            flash("Configurações salvas.", "success")
            return redirect(url_for("settings_view"))
        return render_template("settings.html", settings=settings)

    # ---------- users (admin) ----------
    @app.route("/usuarios")
    @login_required
    @admin_required
    def users_list():
        users = User.query.order_by(User.name).all()
        return render_template("users_list.html", users=users)

    @app.route("/usuarios/novo", methods=["GET", "POST"])
    @login_required
    @admin_required
    def user_new():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            existing = User.query.filter_by(email=email).first()
            if existing:
                flash("Já existe um usuário com esse e-mail.", "danger")
                return render_template("user_form.html", user=None)
            u = User(
                name=request.form.get("name", "").strip(),
                email=email,
                role=request.form.get("role", ROLE_OPERADOR),
            )
            password = request.form.get("password") or "mudar123"
            u.set_password(password)
            if not u.name or not u.email:
                flash("Informe nome e e-mail.", "danger")
                return render_template("user_form.html", user=None)
            db.session.add(u)
            db.session.commit()
            flash(f"Usuário criado. Senha inicial: {password}", "success")
            return redirect(url_for("users_list"))
        return render_template("user_form.html", user=None)

    @app.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
    @login_required
    @admin_required
    def user_edit(user_id):
        u = User.query.get_or_404(user_id)
        if request.method == "POST":
            u.name = request.form.get("name", "").strip()
            u.role = request.form.get("role", ROLE_OPERADOR)
            u.active = request.form.get("active") == "on"
            new_password = request.form.get("password")
            if new_password:
                u.set_password(new_password)
            db.session.commit()
            flash("Usuário atualizado.", "success")
            return redirect(url_for("users_list"))
        return render_template("user_form.html", user=u)

    # ---------- API auxiliar (pré-visualizar período calculado pelo sistema) ----------
    @app.route("/contratos/<int:rental_id>/preview-periodo")
    @login_required
    def preview_periodo(rental_id):
        from flask import jsonify
        r = Rental.query.get_or_404(rental_id)
        issue_date = parse_date(request.args.get("issue_date"), default=date.today())
        start, end = compute_next_rental_period(r, issue_date)
        return jsonify({
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        })

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Você não tem permissão para acessar esta página."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Página não encontrada."), 404

    @app.cli.command("init-db")
    def init_db_command():
        """Cria as tabelas e um usuário admin inicial (flask init-db)."""
        _init_db(app)

    return app


def _migrate_db(app):
    """Adiciona colunas novas em bancos já existentes (sem apagar dados) e
    converte valores antigos de periodicidade para os novos nomes."""
    from sqlalchemy import inspect, text
    with app.app_context():
        inspector = inspect(db.engine)
        if "rentals" not in inspector.get_table_names():
            return
        existing_cols = {c["name"] for c in inspector.get_columns("rentals")}
        statements = []
        if "end_date" not in existing_cols:
            statements.append("ALTER TABLE rentals ADD COLUMN end_date DATE")
        if "adjustment_date" not in existing_cols:
            statements.append("ALTER TABLE rentals ADD COLUMN adjustment_date DATE")
        if "due_day" not in existing_cols:
            statements.append("ALTER TABLE rentals ADD COLUMN due_day INTEGER")
        for stmt in statements:
            db.session.execute(text(stmt))
        if statements:
            db.session.commit()
            print(f"Banco atualizado: {len(statements)} coluna(s) nova(s) adicionada(s).")

        # renomeia periodicidades antigas (ultimos_30/proximos_30) para os novos
        # termos (mes_vencido/mes_vincendo) em contratos e recibos já existentes
        rename_map = [
            ("ultimos_30", "mes_vencido"),
            ("proximos_30", "mes_vincendo"),
        ]
        renamed = 0
        for old, new in rename_map:
            result = db.session.execute(
                text("UPDATE rentals SET default_periodicity = :new WHERE default_periodicity = :old"),
                {"new": new, "old": old},
            )
            renamed += result.rowcount or 0
            result = db.session.execute(
                text("UPDATE receipts SET periodicity = :new WHERE periodicity = :old"),
                {"new": new, "old": old},
            )
            renamed += result.rowcount or 0
        if renamed:
            db.session.commit()
            print(f"Banco atualizado: {renamed} registro(s) com periodicidade renomeada.")


def _init_db(app):
    with app.app_context():
        db.create_all()
        _migrate_db(app)
        if not User.query.filter_by(role=ROLE_ADMIN).first():
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@exemplo.com")
            admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
            admin = User(name="Administrador", email=admin_email, role=ROLE_ADMIN)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"Usuário admin criado: {admin_email} / senha: {admin_password}")
        Settings.get()


app = create_app()

# garante que o banco existe ao iniciar (útil em plataformas que só rodam o start command)
with app.app_context():
    _init_db(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
