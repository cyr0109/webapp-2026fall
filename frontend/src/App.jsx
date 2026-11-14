import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { clearAuth, currentUsername, getToken } from "./api";
import Login from "./Login";
import Groups from "./Groups";
import GroupLayout from "./GroupLayout";
import Ledger from "./Ledger";
import History from "./History";
import Members from "./Members";
import "./index.css";

export default function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(getToken()));

  if (!loggedIn) return <Login onDone={() => setLoggedIn(true)} />;

  return (
    <BrowserRouter>
      <div className="page">
        <div className="masthead">
          <span className="wordmark">分帳簿</span>
          <span className="whoami">
            {currentUsername()}
            <button
              className="quiet"
              onClick={() => {
                clearAuth();
                setLoggedIn(false);
              }}
            >
              登出
            </button>
          </span>
        </div>

        <Routes>
          <Route path="/" element={<Groups />} />
          <Route path="/g/:groupId" element={<GroupLayout />}>
            <Route index element={<Ledger />} />
            <Route path="history" element={<History />} />
            <Route path="members" element={<Members />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
