from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Table, Column, Integer, ForeignKey, String, Boolean, DateTime
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)

# Association table for many-to-many relationship between users and groups
user_groups = Table(
    'user_groups',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('groups.id'), primary_key=True),
)


class Node(db.Model):
    __tablename__ = 'nodes'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    ip_address: Mapped[str] = mapped_column(nullable=False)
    ui_host: Mapped[str] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(nullable=True)
    last_seen: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    def __repr__(self):
        return f'<Node {self.name} @ {self.ip_address}>'


class Group(db.Model):
    __tablename__ = 'groups'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    description: Mapped[str] = mapped_column(nullable=True)

    # Relationship to users
    users: Mapped[list["User"]] = relationship(
        secondary=user_groups,
        back_populates="groups",
    )

    def __repr__(self):
        return f'<Group {self.name}>'


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=True)  # Null for Google users
    role: Mapped[str] = mapped_column(default='user')  # Kept for backward compatibility
    google_id: Mapped[str] = mapped_column(unique=True, nullable=True)

    # Relationship to groups
    groups: Mapped[list[Group]] = relationship(
        secondary=user_groups,
        back_populates="users",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_in_group(self, group_name):
        """Check if user is in a specific group."""
        return any(g.name == group_name for g in self.groups)

    def is_superuser(self):
        return self.is_in_group('superuser')

    def is_admin(self):
        return self.is_in_group('admin') or self.is_superuser()

    def is_team_manager(self):
        return self.is_in_group('team-manager') or self.is_admin()

    def is_engineer(self):
        return self.is_in_group('engineer') or self.is_team_manager()

    def is_reviewer(self):
        """Peer review approver: team-manager, admin, superuser."""
        return self.is_team_manager()


class OAuthConfig(db.Model):
    __tablename__ = 'oauth_config'
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(unique=True, nullable=False)  # 'google'
    client_id: Mapped[str] = mapped_column(nullable=True)
    client_secret: Mapped[str] = mapped_column(nullable=True)
    hd: Mapped[str] = mapped_column(nullable=True)  # hosted domain restriction
    enabled: Mapped[bool] = mapped_column(default=False)

    def __repr__(self):
        return f'<OAuthConfig {self.provider} enabled={self.enabled}>'


class CompanyConfig(db.Model):
    __tablename__ = 'company_config'

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), default='Cudo', nullable=False)
    icon_path: Mapped[str] = mapped_column(String(512), nullable=True)  # relative to static/ (e.g., uploads/company/logo.png)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<CompanyConfig {self.company_name}>'
