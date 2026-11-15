import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import { Boxes, ChartColumn, ScanBarcode, ShieldCheck, Truck, WifiOff } from "lucide-react";
import "@fontsource-variable/inter";
import "./styles.css";
import { getUser, post, saveSession, type User } from "./api";
import { Alert, Field, Toasts, errText, type Message } from "./components";
import { ArmApp } from "./arm/ArmApp";
import { TzdApp } from "./tzd/TzdApp";

registerSW({ immediate: true });

const ARM_ROLES = ["admin", "warehouse_manager", "accountant", "sales_manager"];

export function homeFor(u: User | null): string {
  if (!u) return "/login";
  return u.roles.some((r) => ARM_ROLES.includes(r)) ? "/arm" : "/tzd";
}

const DEMO: [string, string, string][] = [
  ["manager", "Начальник складу", "АРМ + ТЗД"], ["admin", "Адміністратор", "АРМ"], ["accountant", "Бухгалтер", "АРМ"],
  ["sales", "Менеджер з продажу", "АРМ"], ["receiver", "Комірник", "ТЗД · приймання"], ["driver", "Водій навантажувача", "ТЗД · розміщення"],
  ["picker", "Комплектувальник", "ТЗД · відбір"], ["packer", "Контролер", "ТЗД · відвантаження"], ["counter", "Працівник складу", "ТЗД · перерахунок"],
];

function Login() {
  const nav = useNavigate();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [m, setM] = useState<Message>(null);
  const [busy, setBusy] = useState(false);
  const go = async (l = login, p = password) => {
    setBusy(true);
    try {
      const r = await post("/api/auth/login", { login: l, password: p });
      saveSession(r.access_token, r.user);
      nav(homeFor(r.user));
    } catch (e) {
      setM({ kind: "err", text: errText(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-page">
      <div className="login-hero">
        <div className="row-c" style={{ gap: 12 }}>
          <div className="logo" style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(255,255,255,.18)", display: "grid", placeItems: "center" }}><Boxes /></div>
          <b style={{ fontSize: 18 }}>WMS · Склад</b>
        </div>
        <div>
          <h1>Інформаційна система управління складом</h1>
          <p style={{ opacity: .85, marginTop: 12 }}>Прототип за курсовою роботою: від приймання за ASN до відвантаження і звітів.</p>
          <ul>
            <li><ScanBarcode />Приймання, розміщення і відбір зі сканером або камерою (GS1)</li>
            <li><Truck />Контроль комплектності, рампи, заявки в службу доставки</li>
            <li><ChartColumn />KPI табл. 1.1 і звіти ВП-01…ВП-10</li>
            <li><WifiOff />Термінал працює без зв'язку з подальшою синхронізацією</li>
            <li><ShieldCheck />Ролі, журнал операцій, HTTPS</li>
          </ul>
        </div>
        <span className="small" style={{ opacity: .7 }}>Демо-дані узагальнені</span>
      </div>
      <div className="login-form">
        <div className="card stack">
          <div><h2 style={{ marginBottom: 4 }}>Вхід</h2><span className="muted">Увійдіть своїм логіном або оберіть демо-роль</span></div>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); go(); }}>
            <Field label="Логін"><input value={login} onChange={(e) => setLogin(e.target.value)} autoFocus autoComplete="username" /></Field>
            <Field label="Пароль"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></Field>
            <button className="btn btn-block" type="submit" disabled={busy || !login}>Увійти</button>
          </form>
          <Alert m={m} />
          <div>
            <div className="small muted" style={{ marginBottom: 8 }}>Демо-ролі · пароль <code>demo123</code></div>
            <div className="demo-grid">
              {DEMO.map(([l, t, s]) => (
                <button key={l} className="btn btn-secondary" disabled={busy} onClick={() => go(l, "demo123")}><span>{t}</span><small>{s}</small></button>
              ))}
            </div>
          </div>
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
      <Toasts />
    </BrowserRouter>
  </React.StrictMode>,
);
