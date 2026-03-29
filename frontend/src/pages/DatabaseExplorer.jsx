import React, { useState, useEffect } from 'react';
import apiClient from '../utils/apiClient';
import Icon from '../components/Icon';

const DatabaseExplorer = () => {
    const [tables, setTables] = useState([]);
    const [selectedTable, setSelectedTable] = useState('');
    const [tableData, setTableData] = useState(null);
    const [loadingTables, setLoadingTables] = useState(true);
    const [loadingData, setLoadingData] = useState(false);
    const [pagination, setPagination] = useState({ limit: 100, offset: 0, total: 0 });
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchTables = async () => {
            try {
                const response = await apiClient.get('/api/admin/db/tables');
                setTables(response.tables || []);
                if (response.tables && response.tables.length > 0) {
                    setSelectedTable(response.tables[0].name);
                }
                setLoadingTables(false);
            } catch (err) {
                console.error("Failed to fetch tables", err);
                setError("Failed to load tables. Backend might be unreachable.");
                setLoadingTables(false);
            }
        };
        fetchTables();
    }, []);

    useEffect(() => {
        if (!selectedTable) return;

        const fetchData = async () => {
            setLoadingData(true);
            setError(null);
            try {
                const response = await apiClient.get(`/api/admin/db/tables/${selectedTable}`, {
                    params: { limit: pagination.limit, offset: pagination.offset }
                });
                setTableData(response);
                setPagination(prev => ({ ...prev, total: response.pagination.total }));
            } catch (err) {
                console.error(`Failed to fetch data for ${selectedTable}`, err);
                setError(`Failed to load data for ${selectedTable}.`);
            } finally {
                setLoadingData(false);
            }
        };
        fetchData();
    }, [selectedTable, pagination.limit, pagination.offset]);

    const handleNextPage = () => {
        if (pagination.offset + pagination.limit < pagination.total) {
            setPagination(prev => ({ ...prev, offset: prev.offset + prev.limit }));
        }
    };

    const handlePrevPage = () => {
        if (pagination.offset > 0) {
            setPagination(prev => ({ ...prev, offset: Math.max(0, prev.offset - prev.limit) }));
        }
    };

    const handleTableChange = (e) => {
        setSelectedTable(e.target.value);
        setPagination(prev => ({ ...prev, offset: 0, total: 0 }));
        setTableData(null);
    };

    return (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-fade-in relative z-10 pt-16 mt-8">
            <div className="mb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-display font-semibold text-white mb-2 tracking-tight">Database Explorer</h1>
                    <p className="text-slate-400 text-sm max-w-2xl">
                        Interactive viewer for raw SQLite database tables. Provides a direct look into the backend state including model versions, metrics, and training run logs.
                    </p>
                </div>
            </div>

            {error && (
                <div className="mb-6 bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400">
                    <div className="font-semibold mb-1">Error</div>
                    <div className="text-sm">{error}</div>
                </div>
            )}

            <div className="bg-dark-card border border-dark-border rounded-xl mb-6 shadow-xl shadow-black/20 overflow-hidden">
                <div className="p-4 border-b border-dark-border flex flex-wrap gap-4 items-center justify-between bg-dark-bg/30">
                    <div className="flex items-center gap-4 flex-1">
                        <label className="text-sm font-medium text-slate-300">Target Table</label>
                        <select
                            value={selectedTable}
                            onChange={handleTableChange}
                            disabled={loadingTables}
                            className="bg-dark-bg border border-dark-border text-white text-sm rounded-lg focus:ring-accent-blue focus:border-accent-blue p-2.5 min-w-[250px] shadow-inner"
                        >
                            {loadingTables ? (
                                <option>Loading database schema...</option>
                            ) : tables.map(t => (
                                <option key={t.name} value={t.name}>
                                    {t.name} (≈ {t.row_count} rows)
                                </option>
                            ))}
                        </select>
                    </div>

                    {tableData && (
                        <div className="flex items-center gap-4 text-sm text-slate-400 bg-dark-bg/50 py-1.5 px-3 rounded-lg border border-dark-border/50">
                            <span className="font-mono text-xs">Rows {pagination.offset + 1} - {Math.min(pagination.offset + pagination.limit, pagination.total)} of {pagination.total}</span>
                            <div className="flex gap-1 border-l border-dark-border/50 pl-3">
                                <button
                                    onClick={handlePrevPage}
                                    disabled={pagination.offset === 0 || loadingData}
                                    className="p-1.5 rounded hover:bg-dark-border hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                                >
                                    <Icon name="chevron-left" className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={handleNextPage}
                                    disabled={pagination.offset + pagination.limit >= pagination.total || loadingData}
                                    className="p-1.5 rounded hover:bg-dark-border hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                                >
                                    <Icon name="chevron-right" className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                <div className="overflow-x-auto relative min-h-[500px]">
                    {loadingData && (
                        <div className="absolute inset-0 bg-dark-bg/60 backdrop-blur-sm flex items-center justify-center z-10 rounded-b-xl">
                            <div className="w-10 h-10 rounded-full border-4 border-accent-blue/20 border-t-accent-blue animate-spin shadow-[0_0_15px_rgba(59,130,246,0.5)]"></div>
                        </div>
                    )}

                    {!loadingData && tableData && tableData.rows.length === 0 ? (
                        <div className="p-12 text-center flex flex-col items-center justify-center text-slate-400 min-h-[400px]">
                            <Icon name="database" className="w-12 h-12 mb-4 opacity-20" />
                            <p>No records found in table <span className="text-white font-mono text-xs bg-dark-bg px-2 py-1 rounded">{selectedTable}</span></p>
                        </div>
                    ) : tableData && (
                        <table className="w-full text-sm text-left text-slate-300">
                            <thead className="text-[11px] uppercase bg-dark-bg/80 border-b border-dark-border text-slate-500 sticky top-0 z-0">
                                <tr>
                                    {tableData.columns.map(col => (
                                        <th key={col} className="px-6 py-4 font-semibold tracking-wider whitespace-nowrap">
                                            {col}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-dark-border/50">
                                {tableData.rows.map((row, idx) => (
                                    <tr key={idx} className="hover:bg-dark-border/20 transition-colors group">
                                        {tableData.columns.map(col => (
                                            <td key={`${idx}-${col}`} className="px-6 py-3 whitespace-nowrap max-w-[300px] truncate text-slate-300 font-mono text-xs group-hover:text-white" title={String(row[col])}>
                                                {row[col] === null ? (
                                                    <span className="text-slate-600 italic">null</span>
                                                ) : typeof row[col] === 'boolean' ? (
                                                    <span className={`px-2 py-0.5 rounded text-[10px] ${row[col] ? 'bg-green-500/20 text-emerald-400 border border-green-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                                                        {row[col] ? 'TRUE' : 'FALSE'}
                                                    </span>
                                                ) : typeof row[col] === 'object' ? (
                                                    <span className="text-accent-blue/80">
                                                        {JSON.stringify(row[col])}
                                                    </span>
                                                ) : (
                                                    String(row[col])
                                                )}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </div>
    );
};

export default DatabaseExplorer;
