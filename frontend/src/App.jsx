import React, { useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Overview from './pages/Overview'
import DashboardPage from './pages/DashboardPage'
import Simulation from './pages/Simulation'
import ModelIntelligence from './pages/ModelIntelligence'
import MLTraining from './pages/MLTraining'
import SecurityTesting from './pages/SecurityTesting'
import DatabaseExplorer from './pages/DatabaseExplorer'
import Icon from './components/Icon'

function App() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navItems = [
    { path: '/', label: 'Overview', icon: 'grid' },
    { path: '/dashboard', label: 'Dashboard', icon: 'trend' },
    { path: '/simulation', label: 'Simulation', icon: 'play' },
    { path: '/ml-training', label: 'ML Training', icon: 'cpu' },
    { path: '/model-intelligence', label: 'Model Intel', icon: 'chart' },
    { path: '/security-testing', label: 'Security', icon: 'shield' },
    { path: '/database-explorer', label: 'DB Explorer', icon: 'database' },
  ]

  return (
    <div className="min-h-screen gradient-bg">
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-dark-border bg-dark-card/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl border border-accent-blue/60 bg-accent-blue/20 flex items-center justify-center">
                <span className="text-white font-bold text-sm tracking-[0.12em]">PSKC</span>
              </div>
              <div>
                <h1 className="text-white font-display text-xl font-semibold">PSKC</h1>
                <p className="text-xs text-slate-400">Predictive Secure Key Caching</p>
              </div>
            </div>

            <div className="hidden md:flex items-center gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-link flex items-center gap-2 px-4 py-2 rounded-lg ${isActive ? 'active bg-dark-bg/60' : ''}`
                  }
                >
                  <Icon name={item.icon} className="w-4 h-4" />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>

            <button
              className="md:hidden p-2 text-slate-400 hover:text-white"
              onClick={() => setMobileMenuOpen((prev) => !prev)}
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {mobileMenuOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div className="md:hidden bg-dark-card border-b border-dark-border">
            <div className="px-4 py-2 space-y-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-3 rounded-lg ${
                      isActive ? 'bg-accent-blue/20 text-white' : 'text-slate-400 hover:bg-dark-border'
                    }`
                  }
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <Icon name={item.icon} className="w-4 h-4" />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          </div>
        )}
      </nav>

      <main className="pt-16">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/simulation" element={<Simulation />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/ml-training" element={<MLTraining />} />
          <Route path="/model-intelligence" element={<ModelIntelligence />} />
          <Route path="/security-testing" element={<SecurityTesting />} />
          <Route path="/database-explorer" element={<DatabaseExplorer />} />
        </Routes>
      </main>

      <footer className="bg-dark-card/70 border-t border-dark-border py-8 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg border border-accent-blue/60 bg-accent-blue/15 flex items-center justify-center">
                <span className="text-white font-semibold text-xs tracking-[0.12em]">PK</span>
              </div>
              <span className="text-slate-400">PSKC - Predictive Secure Key Caching</span>
            </div>
            <div className="text-slate-500 text-sm">(c) 2026 PSKC Project. All rights reserved.</div>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
