"""Modelos de dados do sistema de recibos de aluguel."""
import builtins
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Tipos de periodicidade suportados
PERIODICIDADE_MES_FECHADO = "mes_fechado"
PERIODICIDADE_MES_VENCIDO = "mes_vencido"
PERIODICIDADE_MES_VINCENDO = "mes_vincendo"

PERIODICIDADE_LABELS = {
    PERIODICIDADE_MES_FECHADO: "Mês fechado (calendário)",
    PERIODICIDADE_MES_VENCIDO: "Mês vencido (cobrado após o período, com base no vencimento)",
    PERIODICIDADE_MES_VINCENDO: "Mês vincendo (cobrado antes do período, com base no vencimento)",
}

STATUS_CAUCAO_A_DEPOSITAR = "a_depositar"
STATUS_CAUCAO_DEPOSITADO = "depositado"

STATUS_CAUCAO_LABELS = {
    STATUS_CAUCAO_A_DEPOSITAR: "A depositar",
    STATUS_CAUCAO_DEPOSITADO: "Depositado",
}

TIPO_RECIBO_ALUGUEL = "aluguel"
TIPO_RECIBO_CAUCAO = "caucao"
TIPO_RECIBO_IPTU = "iptu"
TIPO_RECIBO_OUTROS = "outros"

TIPO_RECIBO_LABELS = {
    TIPO_RECIBO_ALUGUEL: "Aluguel",
    TIPO_RECIBO_CAUCAO: "Caução",
    TIPO_RECIBO_IPTU: "IPTU",
    TIPO_RECIBO_OUTROS: "Outros",
}

ROLE_ADMIN = "admin"
ROLE_OPERADOR = "operador"


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_OPERADOR)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    def get_id(self):
        # Flask-Login exige string
        return str(self.id)

    def __repr__(self):
        return f"<User {self.email}>"


class Client(db.Model):
    """Cliente / inquilino."""
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    document = db.Column(db.String(30))  # CPF ou CNPJ
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    address = db.Column(db.String(300))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Client {self.name}>"


# Tabela de associação: um contrato pode ter mais de um locatário (ex.: casal)
rental_clients = db.Table(
    "rental_clients",
    db.Column("rental_id", db.Integer, db.ForeignKey("rentals.id"), primary_key=True),
    db.Column("client_id", db.Integer, db.ForeignKey("clients.id"), primary_key=True),
)


class Property(db.Model):
    """Imóvel."""
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(150), nullable=False)  # apelido/identificação
    address = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    default_rent_value = db.Column(db.Numeric(10, 2))
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rentals = db.relationship("Rental", back_populates="property")

    def __repr__(self):
        return f"<Property {self.nickname}>"


class Rental(db.Model):
    """Contrato de locação — vincula imóvel + cliente + condições."""
    __tablename__ = "rentals"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)

    rent_value = db.Column(db.Numeric(10, 2), nullable=False)
    default_periodicity = db.Column(db.String(20), nullable=False, default=PERIODICIDADE_MES_FECHADO)
    due_day = db.Column(db.Integer)  # dia do mês em que o aluguel vence (1-31)

    has_deposit = db.Column(db.Boolean, nullable=False, default=False)
    deposit_value = db.Column(db.Numeric(10, 2))
    deposit_status = db.Column(db.String(20))  # a_depositar / depositado
    deposit_date = db.Column(db.Date)  # data em que foi depositado (se aplicável)
    deposit_notes = db.Column(db.Text)

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)  # data de encerramento do contrato
    adjustment_date = db.Column(db.Date)  # próxima data de reajuste do aluguel
    active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    property = db.relationship("Property", back_populates="rentals")
    clients = db.relationship(
        "Client", secondary=rental_clients,
        backref=db.backref("rentals", lazy="dynamic"),
    )
    receipts = db.relationship("Receipt", back_populates="rental", order_by="Receipt.id.desc()")

    @builtins.property
    def clients_names(self):
        return ", ".join(c.name for c in self.clients)

    def __repr__(self):
        return f"<Rental {self.property_id}>"


class Receipt(db.Model):
    """Recibo emitido (histórico)."""
    __tablename__ = "receipts"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)  # ex.: 0001/2026
    rental_id = db.Column(db.Integer, db.ForeignKey("rentals.id"), nullable=False)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    tipo = db.Column(db.String(20), nullable=False, default=TIPO_RECIBO_ALUGUEL)
    value = db.Column(db.Numeric(10, 2), nullable=False)

    periodicity = db.Column(db.String(20))
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)

    issue_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # snapshot de dados no momento da emissão (para reimpressão fiel mesmo que
    # o cadastro do imóvel/cliente mude depois)
    snapshot_property_nickname = db.Column(db.String(150))
    snapshot_property_address = db.Column(db.String(300))
    snapshot_clients_names = db.Column(db.String(300))  # nomes curtos, p/ listagens
    snapshot_clients_text = db.Column(db.Text)  # "Fulano, C.P.F. nº ... e Beltrana, C.P.F. nº ..."
    snapshot_landlord_name = db.Column(db.String(200))
    snapshot_landlord_document = db.Column(db.String(30))
    snapshot_landlord_address = db.Column(db.String(300))
    snapshot_landlord_city = db.Column(db.String(150))

    rental = db.relationship("Rental", back_populates="receipts")
    issued_by = db.relationship("User")

    def __repr__(self):
        return f"<Receipt {self.number}>"


class Settings(db.Model):
    """Configurações gerais (dados do locador para os recibos). Linha única."""
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    landlord_name = db.Column(db.String(200))
    landlord_document = db.Column(db.String(30))  # CPF/CNPJ do locador
    landlord_address = db.Column(db.String(300))
    landlord_city = db.Column(db.String(150))  # cidade usada no fecho do recibo (ex.: "Curvelo")
    landlord_phone = db.Column(db.String(30))
    landlord_email = db.Column(db.String(150))
    receipt_footer_text = db.Column(db.Text)  # texto legal adicional opcional
    next_receipt_seq = db.Column(db.Integer, nullable=False, default=1)

    @staticmethod
    def get():
        settings = Settings.query.first()
        if settings is None:
            settings = Settings(next_receipt_seq=1)
            db.session.add(settings)
            db.session.commit()
        return settings
