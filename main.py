from fastapi import FastAPI, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, String, select, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
import os
import csv
from io import StringIO

# ==========================================
# 1. SECURITY & JWT CONFIGURATION
# ==========================================
SECRET_KEY = "my_super_secret_key_for_development" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8')[:72], hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8')[:72], bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ==========================================
# 2. DATABASE SETUP (CORE MODELS)
# ==========================================
engine = create_engine("sqlite:///finance_app_final.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    email: Mapped[str] = mapped_column(String(50), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(100))

class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200))
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)

class FinanceProfile(Base):
    __tablename__ = "finance_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    monthly_income: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_budget: Mapped[float] = mapped_column(Float, default=0.0)

# ==========================================
# 2.5 "BUDDY SPLIT" DATABASE SETUP
# ==========================================
class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

class GroupMember(Base):
    __tablename__ = "group_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="accepted") # 'pending' or 'accepted'

class GroupExpense(Base):
    __tablename__ = "group_expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    paid_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(200))
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class GroupExpenseSplit(Base):
    __tablename__ = "group_expense_splits"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_expense_id: Mapped[int] = mapped_column(ForeignKey("group_expenses.id"))
    owed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount_owed: Mapped[float] = mapped_column(Float)

class GroupMessage(Base):
    __tablename__ = "group_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(500))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ==========================================
# 3. FASTAPI SETUP & DEPENDENCIES
# ==========================================
app = FastAPI()
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="frontend") 

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: return None
    except jwt.InvalidTokenError:
        return None
    return db.scalars(select(User).where(User.email == email)).first()

def calculate_simplified_debts(group_id: int, db: Session):
    expenses = db.scalars(select(GroupExpense).where(GroupExpense.group_id == group_id)).all()
    balances = {}
    for exp in expenses:
        balances[exp.paid_by_id] = balances.get(exp.paid_by_id, 0) + exp.amount
        splits = db.scalars(select(GroupExpenseSplit).where(GroupExpenseSplit.group_expense_id == exp.id)).all()
        for split in splits:
            balances[split.owed_by_id] = balances.get(split.owed_by_id, 0) - split.amount_owed

    creditors = sorted([(u, amt) for u, amt in balances.items() if amt > 0.01], key=lambda x: x[1])
    debtors = sorted([(u, amt) for u, amt in balances.items() if amt < -0.01], key=lambda x: x[1])
    
    transactions = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt_amt = debtors[i]
        creditor_id, cred_amt = creditors[j]
        settle_amt = min(-debt_amt, cred_amt)
        transactions.append({
            "from": db.get(User, debtor_id).name,
            "to": db.get(User, creditor_id).name,
            "amount": round(settle_amt, 2)
        })
        debtors[i] = (debtor_id, debt_amt + settle_amt)
        creditors[j] = (creditor_id, cred_amt - settle_amt)
        if abs(debtors[i][1]) < 0.01: i += 1
        if abs(creditors[j][1]) < 0.01: j += 1
    return transactions

# ==========================================
# 4. AUTHENTICATION ROUTES 
# ==========================================
@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html")

@app.post("/signup")
def signup_post(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.scalars(select(User).where(User.email == email)).first():
        return templates.TemplateResponse(request=request, name="signup.html", context={"error": "Email already registered."})
    new_user = User(name=name, email=email, hashed_password=get_password_hash(password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(data={"sub": new_user.email})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def login_post(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Invalid email or password."})
    
    access_token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response

# ==========================================
# 5. DASHBOARD & FINANCE ROUTES
# ==========================================
@app.get("/", response_class=HTMLResponse)
def home_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
        
    expenses = db.scalars(select(Expense).where(Expense.user_id == current_user.id).order_by(Expense.date.desc())).all()
    profile = db.scalars(select(FinanceProfile).where(FinanceProfile.user_id == current_user.id)).first()
    
    total_spent = sum(exp.amount for exp in expenses)
    income = profile.monthly_income if profile else 0.0
    budget_amount = profile.monthly_budget if profile else 0.0
    
    return templates.TemplateResponse(request=request, name="index.html", context={
        "expenses": expenses, "current_user": current_user, "total_spent": total_spent,
        "expense_count": len(expenses), "income": income, "budget_amount": budget_amount,
        "balance": income - total_spent, "remaining_budget": budget_amount - total_spent
    })

@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
        
    expenses = db.scalars(select(Expense).where(Expense.user_id == current_user.id).order_by(Expense.date.desc())).all()
    total_spent = sum(exp.amount for exp in expenses)
    
    return templates.TemplateResponse(request=request, name="analytics.html", context={
        "expenses": expenses, "current_user": current_user, "total_spent": total_spent
    })

@app.post("/set_income")
def set_income(amount: float = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    profile = db.scalars(select(FinanceProfile).where(FinanceProfile.user_id == current_user.id)).first()
    if profile: profile.monthly_income = amount
    else: db.add(FinanceProfile(user_id=current_user.id, monthly_income=amount, monthly_budget=0.0))
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/set_budget")
def set_budget(amount: float = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    profile = db.scalars(select(FinanceProfile).where(FinanceProfile.user_id == current_user.id)).first()
    if profile: profile.monthly_budget = amount
    else: db.add(FinanceProfile(user_id=current_user.id, monthly_income=0.0, monthly_budget=amount))
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/create")
def create_expense(amount: float = Form(...), category: str = Form(...), description: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    db.add(Expense(user_id=current_user.id, amount=amount, category=category, description=description))
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/update/{expense_id}", response_class=HTMLResponse)
def update_page(request: Request, expense_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    expense = db.get(Expense, expense_id)
    if not expense or expense.user_id != current_user.id: return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="update.html", context={"expense": expense})

@app.post("/update/{expense_id}")
def update_expense(expense_id: int, amount: float = Form(...), category: str = Form(...), description: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    expense = db.get(Expense, expense_id)
    if expense and expense.user_id == current_user.id:
        expense.amount = amount; expense.category = category; expense.description = description
        db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/delete/{expense_id}")
def delete_expense(expense_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    expense = db.get(Expense, expense_id)
    if expense and expense.user_id == current_user.id: 
        db.delete(expense)
        db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/export")
def export_report(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    expenses = db.scalars(select(Expense).where(Expense.user_id == current_user.id).order_by(Expense.date.desc())).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Category", "Amount (INR)"])
    for exp in expenses:
        writer.writerow([exp.date.strftime('%Y-%m-%d'), exp.description, exp.category, f"{exp.amount:.2f}"])
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=finance_report.csv"
    return response

# ==========================================
# 6. BUDDY SPLIT ROUTES (NEW)
# ==========================================
@app.get("/buddy-split", response_class=HTMLResponse)
def buddy_split_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    
    # Get Accepted Groups
    accepted_links = db.scalars(select(GroupMember).where(GroupMember.user_id == current_user.id, GroupMember.status == "accepted")).all()
    accepted_groups = db.scalars(select(Group).where(Group.id.in_([l.group_id for l in accepted_links]))).all()
    
    # Get Pending Invitations
    pending_links = db.scalars(select(GroupMember).where(GroupMember.user_id == current_user.id, GroupMember.status == "pending")).all()
    pending_groups = db.scalars(select(Group).where(Group.id.in_([l.group_id for l in pending_links]))).all()
    
    return templates.TemplateResponse(request=request, name="buddy_split.html", context={
        "accepted_groups": accepted_groups, "pending_groups": pending_groups, "current_user": current_user
    })

@app.post("/group/create")
def create_group(name: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    new_group = Group(name=name, created_by=current_user.id)
    db.add(new_group)
    db.commit()
    db.refresh(new_group)
    # Creator auto-accepts
    db.add(GroupMember(group_id=new_group.id, user_id=current_user.id, status="accepted"))
    db.commit()
    return RedirectResponse(url=f"/group/{new_group.id}", status_code=303)

@app.get("/group/{group_id}", response_class=HTMLResponse)
def group_detail_page(request: Request, group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    
    # Check access
    member_link = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == current_user.id, GroupMember.status == "accepted")).first()
    if not member_link: return RedirectResponse(url="/buddy-split", status_code=303)
    
    group = db.get(Group, group_id)
    members_links = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.status == "accepted")).all()
    members = db.scalars(select(User).where(User.id.in_([m.user_id for m in members_links]))).all()
    expenses = db.scalars(select(GroupExpense).where(GroupExpense.group_id == group_id).order_by(GroupExpense.date.desc())).all()
    messages = db.scalars(select(GroupMessage).where(GroupMessage.group_id == group_id).order_by(GroupMessage.timestamp.asc())).all()
    
    # Map sender names to messages
    for msg in messages:
        msg.sender_name = db.get(User, msg.sender_id).name

    return templates.TemplateResponse(request=request, name="group_detail.html", context={
        "group": group, "members": members, "expenses": expenses, "messages": messages,
        "debts": calculate_simplified_debts(group_id, db), "current_user": current_user,
        "error": request.query_params.get("error")
    })

@app.post("/group/{group_id}/edit")
def edit_group(group_id: int, name: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(Group, group_id)
    if group.created_by == current_user.id:
        group.name = name
        db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)

@app.post("/group/{group_id}/invite")
def invite_user(group_id: int, email: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_to_add = db.scalars(select(User).where(User.email == email)).first()
    if not user_to_add:
        return RedirectResponse(url=f"/group/{group_id}?error=User not on Expense Buddy", status_code=303)
    
    existing = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_to_add.id)).first()
    if not existing:
        db.add(GroupMember(group_id=group_id, user_id=user_to_add.id, status="pending"))
        db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)

@app.post("/group/{group_id}/accept")
def accept_invite(group_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    link = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == current_user.id)).first()
    if link: link.status = "accepted"; db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)

@app.post("/group/{group_id}/reject")
def reject_invite(group_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    link = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == current_user.id)).first()
    if link: db.delete(link); db.commit()
    return RedirectResponse(url="/buddy-split", status_code=303)

@app.post("/group/{group_id}/kick/{user_id}")
def kick_user(group_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(Group, group_id)
    if group.created_by == current_user.id and user_id != current_user.id:
        link = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)).first()
        if link: db.delete(link); db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)

@app.post("/group/{group_id}/chat")
def post_chat(group_id: int, message: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.add(GroupMessage(group_id=group_id, sender_id=current_user.id, message=message))
    db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)

@app.post("/group/{group_id}/add_expense")
def add_group_expense(group_id: int, description: str = Form(...), amount: float = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_expense = GroupExpense(group_id=group_id, paid_by_id=current_user.id, amount=amount, description=description)
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    
    # Split evenly among ACCEPTED members
    members_links = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.status == "accepted")).all()
    if len(members_links) > 0:
        split_amount = amount / len(members_links)
        for member in members_links:
            db.add(GroupExpenseSplit(group_expense_id=new_expense.id, owed_by_id=member.user_id, amount_owed=split_amount))
    db.commit()
    return RedirectResponse(url=f"/group/{group_id}", status_code=303)