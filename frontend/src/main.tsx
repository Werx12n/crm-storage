import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import "./styles.css";
import { getUser, post, saveSession, type User } from "./api";
import { Msg, errText, type Message } from "./components";
import { ArmApp } from "./arm/ArmApp";
import { TzdApp } from "./tzd/TzdApp";

registerSW({ immediate: true });

export const TZD_ROLES = ["receiver", "forklift_driver", "picker", "packer", "stock_worker"];
export const ARM_ROLES = ["admin", "warehouse_manager", "accountant", "sales_manager"];

export function homeFor(u: User | null): string {
  if (!u) return "/login";
  return u.roles.some((r) => ARM_ROLES.includes(r)) ? "/arm" : "/tzd";
}

const DEMO = [
  ["manager", "Начальник складу"], ["admin", "Адміністратор"], ["accountant", "Бухгалтер"], ["sales", "Менеджер з продажу"],
  ["receiver", "Комірник (ТЗД)"], ["driver", "Водій навантажувача (ТЗД)"], ["picker", "Комплектувальник (ТЗД)"],
  ["packer", "Контролер (ТЗД)"], ["counter", "Працівник складу (ТЗД)"],
];

function Login() {
  const nav = useNavigate();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [m, setM] = useState<Message>(null);
  const go = async (l = login, p = password) => {
    try {
      const r = await post("/api/auth/login", { login: l, password: p });
      saveSession(r.access_token, r.user);
      nav(homeFor(r.user));
    } catch (e) {
      setM({ kind: "err", text: errText(e) });
    }
  };
  return (
    <div className="login">
      <div className="panel">
        <h2>WMS — вхід</h2>
        <form onSubmit={(e) => { e.preventDefault(); go(); }}>
          <label>Логін</label>
          <input value={login} onChange={(e) => setLogin(e.target.value)} autoFocus autoComplete="username" />
          <label>Пароль</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          <button className="btn big" type="submit">Увійти</button>
        </form>
        <Msg m={m} />
        <div className="demo">
          <p className="muted">Демо-користувачі (пароль <code>demo123</code>):</p>
          {DEMO.map(([l, t]) => (
            <button key={l} className="btn btn-sec btn-small" onClick={() => go(l, "demo123")}>{t}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Guard({ children }: { children: React.ReactNode }) {
  return getUser() ? <>{children}</> : <Navigate to="/login" replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/arm/*" element={<Guard><ArmApp /></Guard>} />
        <Route path="/tzd/*" element={<Guard><TzdApp /></Guard>} />
        <Route path="*" element={<Navigate to={homeFor(getUser())} replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
