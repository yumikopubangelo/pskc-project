import React from 'react'
import LiveSimulationDashboard from '../components/LiveSimulationDashboard'
import MLStatus from '../components/MLStatus'

function Simulation() {
  return (
    <div className="container mx-auto space-y-6 p-4 text-white">
      <section className="rounded-2xl border border-dark-border bg-dark-card p-6">
        <div className="max-w-4xl">
          <h1 className="text-2xl font-bold">PSKC Realtime Simulation</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Halaman ini sekarang fokus penuh ke simulasi realtime. Semua angka yang tampil diambil
            dari stream request hidup: model prediction, jalur cache L1/L2, fallback KMS, prefetch
            worker, drift, dan per-key accuracy.
          </p>
        </div>
      </section>

      <MLStatus />
      <LiveSimulationDashboard />
    </div>
  )
}

export default Simulation
