import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import AdminRoute from './components/AdminRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import FeedbackStats from './pages/FeedbackStats';
import UserManagement from './pages/UserManagement';
import AdminLogs from './pages/AdminLogs';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          {/* 反馈统计（所有登录用户可访问） */}
          <Route
            path="/feedback"
            element={
              <ProtectedRoute>
                <FeedbackStats />
              </ProtectedRoute>
            }
          />
          {/* admin 专属：用户管理 */}
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute>
                <AdminRoute>
                  <UserManagement />
                </AdminRoute>
              </ProtectedRoute>
            }
          />
          {/* admin 专属：日志管理 */}
          <Route
            path="/admin/logs"
            element={
              <ProtectedRoute>
                <AdminRoute>
                  <AdminLogs />
                </AdminRoute>
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;