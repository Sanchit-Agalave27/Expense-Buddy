from fastapi import FastAPI, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, String, select, Float, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
import os
from typing import Optional

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
# 2. DATABASE SETUP (Added Budget Model)
# ==========================================
engine = create_engine("sqlite:///finance_app_v2.db", connect_args={"check_same_thread": False})
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

class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True) # One budget per user for now
    amount: Mapped[float] = mapped_column(Float)

Base.metadata.create_all(bind=engine)

# ==========================================
# 3. FASTAPI SETUP & DEPENDENCIES
# ==========================================
app = FastAPI()
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="Frontend") 

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

# ==========================================
# 4. AUTHENTICATION ROUTES 
# ==========================================
@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html")

@app.post("/signup")
def signup_post(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing_user = db.scalars(select(User).where(User.email == email)).first()
    if existing_user:
        return templates.TemplateResponse(request=request, name="signup.html", context={"error": "Email already registered."})
    
    new_user = User(name=name, email=email, hashed_password=get_password_hash(password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user) # Added refresh
    
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
# 5. PROTECTED APP ROUTES (Dashboard & CRUD)
# ==========================================
@app.get("/", response_class=HTMLResponse)
def home_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
        
    expenses = db.scalars(select(Expense).where(Expense.user_id == current_user.id).order_by(Expense.date.desc())).all()
    user_budget = db.scalars(select(Budget).where(Budget.user_id == current_user.id)).first()
    
    total_spent = sum(exp.amount for exp in expenses)
    expense_count = len(expenses)
    budget_amount = user_budget.amount if user_budget else 0.0
    remaining_budget = budget_amount - total_spent
    
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "expenses": expenses, 
            "current_user": current_user, 
            "total_spent": total_spent,
            "expense_count": expense_count,
            "budget_amount": budget_amount,
            "remaining_budget": remaining_budget
        }
    )

@app.post("/set_budget")
def set_budget(amount: float = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    
    user_budget = db.scalars(select(Budget).where(Budget.user_id == current_user.id)).first()
    if user_budget:
        user_budget.amount = amount
    else:
        new_budget = Budget(user_id=current_user.id, amount=amount)
        db.add(new_budget)
        
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/create")
def create_expense(amount: float = Form(...), category: str = Form(...), description: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    
    new_expense = Expense(user_id=current_user.id, amount=amount, category=category, description=description)
    db.add(new_expense)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/update/{expense_id}", response_class=HTMLResponse)
def update_page(request: Request, expense_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    expense = db.get(Expense, expense_id)
    if not expense or expense.user_id != current_user.id:
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse(request=request, name="update.html", context={"expense": expense})

@app.post("/update/{expense_id}")
def update_expense(expense_id: int, amount: float = Form(...), category: str = Form(...), description: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user: return RedirectResponse(url="/login", status_code=303)
    
    expense = db.get(Expense, expense_id)
    if expense and expense.user_id == current_user.id:
        expense.amount = amount
        expense.category = category
        expense.description = description
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