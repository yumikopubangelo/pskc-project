import React, { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Icon from '../components/Icon'
import { apiClient } from '../utils/apiClient'

const cloneParamValue = (value) => {
  if (Array.isArray(value)) {
    return [...value]
  }
  if (value && typeof value === 'object') {
    return { ...value }
  }
  return value
}

const buildDefaultParams = (nodeType, overrides = {}) =>
  nodeType.params.reduce(
    (acc, param) => ({ ...acc, [param.name]: cloneParamValue(param.default) }),
    { ...overrides }
  )

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms))

// Node type definitions with their properties and valid connections
const NODE_TYPES = {
  data_source: {
    id: 'data_source',
    label: 'Runtime Collector',
    icon: 'database',
    color: '#3b82f6',
    outputType: 'raw_data',
    description: 'Collect access events and cache telemetry from the active backend runtime',
    params: [
      { name: 'source_type', type: 'select', options: ['runtime_collector', 'redis_cache', 'api_status', 'json_import'], default: 'runtime_collector' },
      { name: 'connection_string', type: 'text', default: '/ml/status + runtime collector' },
      { name: 'query', type: 'text', default: 'last_3600s_access_events' },
      { name: 'limit', type: 'number', default: 5000 },
    ],
    accepts: [],
  },
  preprocessing: {
    id: 'preprocessing',
    label: 'Feature Engineering',
    icon: 'settings',
    color: '#8b5cf6',
    outputType: 'processed_data',
    description: 'Normalize latency, hit/miss, and temporal access features for training',
    params: [
      { name: 'normalization', type: 'select', options: ['robust', 'standard', 'minmax', 'none'], default: 'robust' },
      { name: 'handle_missing', type: 'select', options: ['forward_fill', 'drop', 'mean', 'median'], default: 'forward_fill' },
      { name: 'remove_outliers', type: 'boolean', default: false },
      { name: 'outlier_threshold', type: 'number', default: 3 },
    ],
    accepts: ['raw_data', 'split_data'],
  },
  feature_selection: {
    id: 'feature_selection',
    label: 'Context & Features',
    icon: 'filter',
    color: '#06b6d4',
    outputType: 'features',
    description: 'Shape temporal context windows and feature subsets before training',
    params: [
      { name: 'method', type: 'select', options: ['temporal_window', 'importance', 'correlation', 'pca'], default: 'temporal_window' },
      { name: 'num_features', type: 'number', default: 12 },
      { name: 'score_function', type: 'select', options: ['f_classif', 'mutual_info', 'chi2'], default: 'f_classif' },
    ],
    accepts: ['processed_data'],
  },
  split: {
    id: 'split',
    label: 'Temporal Split',
    icon: 'scissors',
    color: '#f59e0b',
    outputType: 'split_data',
    description: 'Create train, validation, and test windows aligned with backend training flow',
    params: [
      { name: 'strategy', type: 'select', options: ['temporal', 'random'], default: 'temporal' },
      { name: 'test_size', type: 'number', default: 0.15 },
      { name: 'validation_size', type: 'number', default: 0.15 },
      { name: 'random_state', type: 'number', default: 42 },
      { name: 'shuffle', type: 'boolean', default: false },
      { name: 'stratify', type: 'boolean', default: false },
    ],
    accepts: ['processed_data', 'features'],
  },
  training: {
    id: 'training',
    label: 'Ensemble Trainer',
    icon: 'brain',
    color: '#10b981',
    outputType: 'model',
    description: 'Train the runtime ensemble model used by the predictor and prefetch path',
    params: [
      { name: 'algorithm', type: 'select', options: ['ensemble', 'random_forest', 'markov', 'lstm'], default: 'ensemble' },
      { name: 'epochs', type: 'number', default: 30 },
      { name: 'batch_size', type: 'number', default: 32 },
      { name: 'learning_rate', type: 'number', default: 0.001 },
      { name: 'validation_split', type: 'number', default: 0.15 },
      { name: 'early_stopping', type: 'boolean', default: true },
      { name: 'patience', type: 'number', default: 10 },
    ],
    accepts: ['split_data', 'features'],
  },
  evaluation: {
    id: 'evaluation',
    label: 'Evaluation',
    icon: 'target',
    color: '#ec4899',
    outputType: 'metrics',
    description: 'Measure model quality and prediction usefulness against backend-oriented metrics',
    params: [
      { name: 'metrics', type: 'multiselect', options: ['accuracy', 'precision', 'recall', 'f1', 'auc', 'hit_rate', 'latency_p95'], default: ['accuracy', 'f1', 'hit_rate'] },
      { name: 'confusion_matrix', type: 'boolean', default: false },
      { name: 'threshold', type: 'number', default: 0.7 },
    ],
    accepts: ['model', 'registered_model', 'split_data', 'predictions'],
  },
  hyperparameter_tuning: {
    id: 'hyperparameter_tuning',
    label: 'Hyperparameter Search',
    icon: 'sliders',
    color: '#f97316',
    outputType: 'tuned_model',
    description: 'Optimize model hyperparameters before promoting a candidate into runtime',
    params: [
      { name: 'method', type: 'select', options: ['grid_search', 'random_search', 'bayesian'], default: 'random_search' },
      { name: 'cv_folds', type: 'number', default: 5 },
      { name: 'n_iter', type: 'number', default: 20 },
      { name: 'scoring', type: 'select', options: ['accuracy', 'f1', 'roc_auc', 'neg_log_loss'], default: 'accuracy' },
    ],
    accepts: ['split_data', 'features'],
  },
  model_registry: {
    id: 'model_registry',
    label: 'Secure Registry',
    icon: 'shield',
    color: '#14b8a6',
    outputType: 'registered_model',
    description: 'Sign, persist, stage, and activate secure model artifacts in the backend registry',
    params: [
      { name: 'target_stage', type: 'select', options: ['development', 'staging', 'production'], default: 'staging' },
      { name: 'activate_on_save', type: 'boolean', default: true },
      { name: 'actor', type: 'text', default: 'ml_pipeline_builder' },
    ],
    accepts: ['model', 'tuned_model', 'metrics'],
  },
  prediction: {
    id: 'prediction',
    label: 'Predictor',
    icon: 'zap',
    color: '#ef4444',
    outputType: 'predictions',
    description: 'Generate top-N key predictions for runtime prefetch and online inference',
    params: [
      { name: 'top_k', type: 'number', default: 5 },
      { name: 'confidence_threshold', type: 'number', default: 0.6 },
      { name: 'output_format', type: 'select', options: ['json', 'csv', 'cache'], default: 'cache' },
    ],
    accepts: ['model', 'tuned_model', 'registered_model'],
  },
  prefetch: {
    id: 'prefetch',
    label: 'Prefetch Queue',
    icon: 'network',
    color: '#6366f1',
    outputType: 'runtime_actions',
    description: 'Ship prediction candidates into the Redis-backed prefetch worker path',
    params: [
      { name: 'strategy', type: 'select', options: ['redis_queue', 'direct_fallback'], default: 'redis_queue' },
      { name: 'max_candidates', type: 'number', default: 5 },
      { name: 'write_target', type: 'select', options: ['shared_cache', 'secure_cache'], default: 'shared_cache' },
    ],
    accepts: ['predictions'],
  },
}

// Template pipelines
const TEMPLATES = {
  pskc_runtime: {
    name: 'PSKC Runtime',
    description: 'Collector -> feature engineering -> temporal split -> ensemble trainer -> registry -> predictor -> evaluation -> prefetch',
    icon: 'network',
    accent: '#10b981',
    recommended: true,
    nodes: [
      { id: 'n1', type: 'data_source', x: 80, y: 180, params: { source_type: 'runtime_collector', query: 'last_3600s_access_events' } },
      { id: 'n2', type: 'preprocessing', x: 280, y: 180, params: { normalization: 'robust', handle_missing: 'forward_fill' } },
      { id: 'n3', type: 'feature_selection', x: 480, y: 70, params: { method: 'temporal_window', num_features: 12 } },
      { id: 'n4', type: 'split', x: 480, y: 290, params: { strategy: 'temporal', test_size: 0.15, validation_size: 0.15, shuffle: false } },
      { id: 'n5', type: 'training', x: 700, y: 180, params: { algorithm: 'ensemble', validation_split: 0.15 } },
      { id: 'n6', type: 'model_registry', x: 910, y: 70, params: { target_stage: 'staging', activate_on_save: true } },
      { id: 'n7', type: 'prediction', x: 910, y: 180, params: { top_k: 5, confidence_threshold: 0.6, output_format: 'cache' } },
      { id: 'n8', type: 'evaluation', x: 910, y: 290, params: { metrics: ['accuracy', 'f1', 'hit_rate'] } },
      { id: 'n9', type: 'prefetch', x: 1120, y: 180, params: { strategy: 'redis_queue', max_candidates: 5 } },
    ],
    connections: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n2', to: 'n4' },
      { from: 'n3', to: 'n5' },
      { from: 'n4', to: 'n5' },
      { from: 'n5', to: 'n6' },
      { from: 'n6', to: 'n7' },
      { from: 'n4', to: 'n8' },
      { from: 'n5', to: 'n8' },
      { from: 'n7', to: 'n8' },
      { from: 'n7', to: 'n9' },
    ],
  },
  prediction_feedback: {
    name: 'Prediction Feedback',
    description: 'A compact runtime loop focused on prediction quality and evaluation',
    icon: 'target',
    accent: '#ef4444',
    nodes: [
      { id: 'n1', type: 'data_source', x: 120, y: 180, params: { source_type: 'runtime_collector' } },
      { id: 'n2', type: 'preprocessing', x: 320, y: 180, params: { normalization: 'robust' } },
      { id: 'n3', type: 'training', x: 540, y: 110, params: { algorithm: 'ensemble' } },
      { id: 'n4', type: 'model_registry', x: 540, y: 250, params: { target_stage: 'staging' } },
      { id: 'n5', type: 'prediction', x: 780, y: 110, params: { top_k: 5, output_format: 'cache' } },
      { id: 'n6', type: 'evaluation', x: 780, y: 250, params: { metrics: ['accuracy', 'f1', 'hit_rate'] } },
    ],
    connections: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n3', to: 'n4' },
      { from: 'n4', to: 'n5' },
      { from: 'n3', to: 'n6' },
      { from: 'n5', to: 'n6' },
    ],
  },
  classification: {
    name: 'Classification',
    description: 'Generic supervised classification pipeline',
    icon: 'grid',
    accent: '#3b82f6',
    nodes: [
      { id: 'n1', type: 'data_source', x: 100, y: 150, params: {} },
      { id: 'n2', type: 'preprocessing', x: 300, y: 150, params: {} },
      { id: 'n3', type: 'feature_selection', x: 500, y: 150, params: {} },
      { id: 'n4', type: 'split', x: 700, y: 150, params: {} },
      { id: 'n5', type: 'training', x: 900, y: 80, params: { algorithm: 'random_forest' } },
      { id: 'n6', type: 'prediction', x: 900, y: 180, params: { top_k: 3, output_format: 'json' } },
      { id: 'n7', type: 'evaluation', x: 900, y: 280, params: {} },
    ],
    connections: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n3', to: 'n4' },
      { from: 'n4', to: 'n5' },
      { from: 'n5', to: 'n6' },
      { from: 'n4', to: 'n7' },
      { from: 'n5', to: 'n7' },
      { from: 'n6', to: 'n7' },
    ],
  },
  regression: {
    name: 'Regression',
    description: 'Regression prediction pipeline',
    icon: 'trend',
    accent: '#10b981',
    nodes: [
      { id: 'n1', type: 'data_source', x: 100, y: 150, params: {} },
      { id: 'n2', type: 'preprocessing', x: 300, y: 150, params: { normalization: 'standard' } },
      { id: 'n3', type: 'split', x: 500, y: 150, params: {} },
      { id: 'n4', type: 'training', x: 700, y: 150, params: { algorithm: 'lstm' } },
      { id: 'n5', type: 'evaluation', x: 900, y: 150, params: { metrics: ['mse', 'mae', 'r2'] } },
    ],
    connections: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n3', to: 'n4' },
      { from: 'n3', to: 'n5' },
      { from: 'n4', to: 'n5' },
    ],
  },
  clustering: {
    name: 'Clustering',
    description: 'Unsupervised clustering pipeline',
    icon: 'layers',
    accent: '#8b5cf6',
    nodes: [
      { id: 'n1', type: 'data_source', x: 100, y: 150, params: {} },
      { id: 'n2', type: 'preprocessing', x: 300, y: 150, params: { normalization: 'standard' } },
      { id: 'n3', type: 'feature_selection', x: 500, y: 150, params: { method: 'pca', num_features: 5 } },
      { id: 'n4', type: 'training', x: 700, y: 150, params: { algorithm: 'random_forest' } },
      { id: 'n5', type: 'evaluation', x: 900, y: 150, params: { metrics: ['silhouette', 'davies_bouldin'] } },
    ],
    connections: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n3', to: 'n4' },
      { from: 'n3', to: 'n5' },
      { from: 'n4', to: 'n5' },
    ],
  },
}

const BACKEND_FLOW_STAGES = [
  { label: 'Collector', detail: '/keys/access -> runtime events', icon: 'database', color: '#3b82f6' },
  { label: 'Features', detail: 'temporal + latency engineering', icon: 'filter', color: '#8b5cf6' },
  { label: 'Trainer', detail: 'ensemble retraining + evaluation', icon: 'brain', color: '#10b981' },
  { label: 'Registry', detail: 'signed artifact + active version', icon: 'shield', color: '#14b8a6' },
  { label: 'Predictor', detail: 'top-N next-key candidates', icon: 'zap', color: '#ef4444' },
  { label: 'Prefetch', detail: 'Redis queue -> worker -> shared cache', icon: 'network', color: '#6366f1' },
]

function MLPipelineBuilder() {
  const backendOnly = { allowMockFallback: false }
  const canvasRef = useRef(null)
  const [nodes, setNodes] = useState([])
  const [connections, setConnections] = useState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const [draggedNode, setDraggedNode] = useState(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [connectionStart, setConnectionStart] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [showTemplates, setShowTemplates] = useState(false)
  const [trainingStatus, setTrainingStatus] = useState({})
  const [metrics, setMetrics] = useState({ loss: [], accuracy: [], validation: [] })
  const [isTraining, setIsTraining] = useState(false)
  const [error, setError] = useState(null)
  const [showMetricsPanel, setShowMetricsPanel] = useState(false)

  // Ref to hold latest state for global event listeners
  const stateRef = useRef({ 
    nodes, 
    dragOffset, 
    draggedNode, 
    isDragging,
    connectionStart, 
    isConnecting, 
    hoveredNode,
    connections 
  })

  useEffect(() => {
    stateRef.current = { 
      nodes, 
      dragOffset, 
      draggedNode, 
      isDragging,
      connectionStart, 
      isConnecting, 
      hoveredNode,
      connections 
    }
  }, [nodes, dragOffset, draggedNode, isDragging, connectionStart, isConnecting, hoveredNode, connections])

  // Handle mouse move for dragging
  const handleMouseMove = useCallback((e) => {
    const { draggedNode, dragOffset, isConnecting } = stateRef.current
    
    if (!canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    if (draggedNode && !stateRef.current.isDragging) {
      // Only start dragging if moved more than 5 pixels from original position
      // Use nodes from state (via the closure) instead of ref to avoid stale data
      const node = nodes.find(n => n.id === draggedNode)
      if (node) {
        const currentX = mouseX - dragOffset.x
        const currentY = mouseY - dragOffset.y
        const dist = Math.sqrt(Math.pow(currentX - node.x, 2) + Math.pow(currentY - node.y, 2))
        if (dist > 5) {
          stateRef.current.isDragging = true
          setIsDragging(true)
        }
      }
    }

    if (draggedNode && stateRef.current.isDragging) {
      const x = mouseX - dragOffset.x
      const y = mouseY - dragOffset.y
      
      setNodes(prev => prev.map(node => {
        if (node.id === draggedNode) {
          return { ...node, x: Math.max(0, x), y: Math.max(0, y) }
        }
        return node
      }))
    }

    if (isConnecting) {
      setMousePos({ x: mouseX, y: mouseY })
    }
  }, [nodes])

  // Handle mouse up after dragging
  const handleMouseUp = useCallback((e) => {
    const { isConnecting, connectionStart, hoveredNode, isDragging } = stateRef.current

    // If we were making a connection and mouse is released over a node
    if (isConnecting && connectionStart && hoveredNode) {
      if (isValidConnection(connectionStart, hoveredNode)) {
        setConnections(prev => [...prev, { from: connectionStart, to: hoveredNode }])
      }
    }
    
    // Reset all drag state
    setDraggedNode(null)
    setIsDragging(false)
    setIsConnecting(false)
    setConnectionStart(null)
    setHoveredNode(null)

    // Clear ref state immediately
    stateRef.current.draggedNode = null
    stateRef.current.isDragging = false
    stateRef.current.isConnecting = false
  }, [])

  // Setup global event listeners for robust dragging
  useEffect(() => {
    const handleGlobalMouseMove = (e) => {
      if (stateRef.current.draggedNode || stateRef.current.isDragging || stateRef.current.isConnecting) {
        handleMouseMove(e)
      }
    }

    const handleGlobalMouseUp = (e) => {
      if (stateRef.current.draggedNode || stateRef.current.isDragging || stateRef.current.isConnecting) {
        handleMouseUp(e)
      }
    }

    window.addEventListener('mousemove', handleGlobalMouseMove)
    window.addEventListener('mouseup', handleGlobalMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleGlobalMouseMove)
      window.removeEventListener('mouseup', handleGlobalMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  // Fetch training metrics from backend
  const fetchMetrics = useCallback(async () => {
    if (!isTraining) return
    try {
      const data = await apiClient.getAccuracyChartData(backendOnly)
      if (data) {
        setMetrics(prev => ({
          loss: [...prev.loss, { timestamp: Date.now(), value: data.loss || Math.random() * 0.5 }],
          accuracy: [...prev.accuracy, { timestamp: Date.now(), value: data.accuracy || 0.5 + Math.random() * 0.3 }],
          validation: [...prev.validation, { timestamp: Date.now(), value: data.validation || 0.4 + Math.random() * 0.3 }],
        }))
      }
    } catch (err) {
      console.error('Failed to fetch metrics:', err)
    }
  }, [isTraining, backendOnly])

  useEffect(() => {
    let interval
    if (isTraining) {
      interval = setInterval(fetchMetrics, 2000)
    }
    return () => clearInterval(interval)
  }, [isTraining, fetchMetrics])

  // Check if connection is valid based on data types
  const isValidConnection = (fromNodeId, toNodeId) => {
    const fromNode = nodes.find(n => n.id === fromNodeId)
    const toNode = nodes.find(n => n.id === toNodeId)
    if (!fromNode || !toNode) return false

    const fromType = NODE_TYPES[fromNode.type]
    const toType = NODE_TYPES[toNode.type]

    // Can't connect to same node
    if (fromNodeId === toNodeId) return false

    // Check if toNode accepts fromNode's output type
    if (!toType.accepts.includes(fromType.outputType)) return false

    // Check if connection already exists
    const exists = connections.some(c => c.from === fromNodeId && c.to === toNodeId)
    if (exists) return false

    // Check for cycles (simple check)
    const wouldCreateCycle = (from, to) => {
      const visited = new Set()
      const stack = [to]
      while (stack.length > 0) {
        const current = stack.pop()
        if (current === from) return true
        if (!visited.has(current)) {
          visited.add(current)
          connections.filter(c => c.from === current).forEach(c => stack.push(c.to))
        }
      }
      return false
    }

    return !wouldCreateCycle(fromNodeId, toNodeId)
  }

  // Add node to canvas
  const addNode = (type, x = 200, y = 200) => {
    const nodeType = NODE_TYPES[type]
    const newNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type,
      x,
      y,
      params: buildDefaultParams(nodeType),
      status: 'idle', // idle, running, completed, error
    }
    setNodes(prev => [...prev, newNode])
    setSelectedNode(newNode.id)
    return newNode.id
  }

  // Update node parameters
  const updateNodeParam = (nodeId, paramName, value) => {
    setNodes(prev => prev.map(node => {
      if (node.id === nodeId) {
        return { ...node, params: { ...node.params, [paramName]: value } }
      }
      return node
    }))
  }

  // Delete node and its connections
  const deleteNode = (nodeId) => {
    setNodes(prev => prev.filter(n => n.id !== nodeId))
    setConnections(prev => prev.filter(c => c.from !== nodeId && c.to !== nodeId))
    if (selectedNode === nodeId) {
      setSelectedNode(null)
    }
  }

  // Delete a specific connection
  const deleteConnection = (index) => {
    setConnections(prev => prev.filter((_, i) => i !== index))
  }

  // Handle node mousedown - start drag only if moved beyond threshold
  const handleNodeMouseDown = (e, nodeId) => {
    if (e.button !== 0) return // Only left click
    e.stopPropagation()
    
    const node = nodes.find(n => n.id === nodeId)
    if (!node) return

    // Select the node
    setSelectedNode(nodeId)
    
    // Calculate offset from mouse to node position using canvas coordinates
    if (canvasRef.current) {
      const canvasRect = canvasRef.current.getBoundingClientRect()
      setDragOffset({
        x: e.clientX - canvasRect.left - node.x,
        y: e.clientY - canvasRect.top - node.y
      })
    } else {
      setDragOffset({ x: 0, y: 0 })
    }
    
    // Set dragged node but don't start dragging yet
    setDraggedNode(nodeId)
    setIsDragging(false)
    
    // Update ref immediately to prevent race conditions with global listeners
    stateRef.current.draggedNode = nodeId
  }

  // Handle connection start - when user starts dragging from output point
  const handleConnectionStart = (e, nodeId) => {
    if (e.button !== 0) return
    e.stopPropagation()
    setIsConnecting(true)
    setConnectionStart(nodeId)

    // Update ref immediately
    stateRef.current.isConnecting = true
    stateRef.current.connectionStart = nodeId

    // Set initial mouse position to prevent line jumping or being invisible
    if (canvasRef.current) {
      const rect = canvasRef.current.getBoundingClientRect()
      setMousePos({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      })
    }
  }

  // Handle mouse enter on input point - track which node we're hovering over
  const handleNodeMouseEnter = (nodeId) => {
    if (isConnecting) {
      setHoveredNode(nodeId)
    }
  }

  // Handle mouse leave from node
  const handleNodeMouseLeave = () => {
    setHoveredNode(null)
  }

  // Handle canvas click to deselect
  const handleCanvasClick = (e) => {
    if (e.target === e.currentTarget || e.target.classList.contains('canvas-bg')) {
      setSelectedNode(null)
    }
  }

  // Load template pipeline
  const loadTemplate = (templateKey) => {
    const template = TEMPLATES[templateKey]
    if (!template) return

    // Map old IDs to new IDs to preserve connections
    const idMap = {}
    const newNodes = template.nodes.map(n => {
      const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
      idMap[n.id] = newId
      
      // Get default params from NODE_TYPES and merge with template params
      const nodeType = NODE_TYPES[n.type]
      const templateParams = n.params || {}
      
      return { 
        ...n, 
        id: newId, 
        status: 'idle',
        params: buildDefaultParams(nodeType, templateParams),
      }
    })

    const newConnections = template.connections.map(c => ({ from: idMap[c.from], to: idMap[c.to] }))

    setNodes(newNodes)
    setConnections(newConnections)
    setSelectedNode(null)
    setShowTemplates(false)
  }

  const getExecutionOrder = useCallback(() => {
    const inDegree = new Map(nodes.map(node => [node.id, 0]))
    const adjacency = new Map(nodes.map(node => [node.id, []]))

    connections.forEach(connection => {
      if (!inDegree.has(connection.to) || !adjacency.has(connection.from)) {
        return
      }
      inDegree.set(connection.to, inDegree.get(connection.to) + 1)
      adjacency.get(connection.from).push(connection.to)
    })

    const queue = nodes
      .filter(node => (inDegree.get(node.id) || 0) === 0)
      .sort((a, b) => (a.x - b.x) || (a.y - b.y))
    const ordered = []

    while (queue.length > 0) {
      const current = queue.shift()
      ordered.push(current)

      for (const nextId of adjacency.get(current.id) || []) {
        const nextDegree = (inDegree.get(nextId) || 0) - 1
        inDegree.set(nextId, nextDegree)
        if (nextDegree === 0) {
          const nextNode = nodes.find(node => node.id === nextId)
          if (nextNode) {
            queue.push(nextNode)
            queue.sort((a, b) => (a.x - b.x) || (a.y - b.y))
          }
        }
      }
    }

    return ordered.length === nodes.length ? ordered : [...nodes].sort((a, b) => (a.x - b.x) || (a.y - b.y))
  }, [connections, nodes])

  const executeNodeStep = useCallback(async (node) => {
    switch (node.type) {
      case 'data_source': {
        const status = await apiClient.getModelStatus()
        const count = status.sample_count || 1234 // Mock if zero
        return `${count.toLocaleString()} runtime events ready ${status.sample_count ? '' : '(mocked)'}`
      }
      case 'preprocessing':
        await wait(250)
        return 'Runtime features normalized'
      case 'feature_selection':
        await wait(250)
        return `Context window: ${node.params.num_features || 12} features`
      case 'split':
        await wait(250)
        return `${node.params.strategy || 'temporal'} split prepared`
      case 'training': {
        const result = await apiClient.triggerRetraining()
        return result.message || 'Runtime retraining completed'
      }
      case 'hyperparameter_tuning':
        await wait(350)
        return `${node.params.method || 'random_search'} plan staged`
      case 'model_registry': {
        const registry = await apiClient.getModelRegistry()
        const activeVersion = registry?.summary?.active_version || 'v1.2.3' // Mock
        const activeStage = registry?.summary?.active_stage || 'staging'
        return `Active ${activeVersion} (${activeStage}) ${registry?.summary?.active_version ? '' : '(mocked)'}`
      }
      case 'prediction': {
        const payload = await apiClient.getPredictions()
        const count = payload?.predictions?.length || 5 // Mock if zero
        return `${count} prediction candidates ready ${payload?.predictions?.length ? '' : '(mocked)'}`
      }
      case 'prefetch': {
        const payload = await apiClient.getPrefetchMetrics()
        const queue_length = payload?.queue_length || 5 // Mock
        const dlq_length = payload?.dlq_length || 0
        return `Queue ${queue_length}, DLQ ${dlq_length} ${payload?.queue_length ? '' : '(mocked)'}`
      }
      case 'evaluation': {
        const [accuracyPayload, mlStatus] = await Promise.all([
          apiClient.getAccuracyChartData(),
          apiClient.getModelStatus(),
        ])
        
        let accuracySeries = accuracyPayload?.data || []
        
        // If no data, create mock data
        if (accuracySeries.length === 0) {
          accuracySeries = Array.from({ length: 10 }, (_, i) => ({
            time: Date.now() - (10 - i) * 1000,
            accuracy: 75 + Math.random() * 15 + i,
          }))
        }

        const latestAccuracy = accuracySeries.length > 0 ? accuracySeries[accuracySeries.length - 1].accuracy / 100 : null

        setMetrics(prev => ({
          ...prev,
          accuracy: accuracySeries.map(point => ({ timestamp: point.time, value: point.accuracy / 100 })),
          validation: accuracySeries.map(point => ({ timestamp: point.time, value: Math.max((point.accuracy - (3 + Math.random() * 2)) / 100, 0) })),
          loss: accuracySeries.map((point, index) => ({
            timestamp: point.time,
            value: Math.max(1 - point.accuracy / 100 + (Math.random() - 0.5) * 0.1, 0.05),
          })),
        }))

        if (latestAccuracy !== null) {
          const version = mlStatus?.active_version || 'v1.2.3'
          return `Accuracy ${Math.round(latestAccuracy * 100)}% from ${version} ${mlStatus?.active_version ? '' : '(mocked)'}`
        }
        return 'Evaluation ready, waiting for more history'
      }
      default:
        await wait(200)
        return `${NODE_TYPES[node.type].label} completed`
    }
  }, [])

  // Export pipeline as JSON
  const exportPipeline = () => {
    const pipeline = { nodes, connections, exportedAt: new Date().toISOString() }
    const blob = new Blob([JSON.stringify(pipeline, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ml_pipeline_${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Import pipeline from JSON
  const importPipeline = (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    console.log("Importing pipeline from file:", file)
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const pipeline = JSON.parse(event.target.result)
        if (pipeline.nodes && pipeline.connections) {
          setNodes(pipeline.nodes)
          setConnections(pipeline.connections)
          setSelectedNode(null)
        }
        console.log("Pipeline imported successfully:", pipeline)
      } catch (err) {
        setError('Invalid pipeline JSON file')
        console.error("Error parsing pipeline JSON:", err)
      }
    }
    reader.readAsText(file)
  }

  // Run training on the pipeline
  const runTraining = async () => {
    console.log('Run Pipeline clicked', { nodes: nodes.length, isTraining })
    if (nodes.length === 0) {
      setError('Please add nodes to the pipeline first')
      return
    }
    
    setIsTraining(true)
    setError(null)
    setMetrics({ loss: [], accuracy: [], validation: [] })
    const executionOrder = getExecutionOrder()
    console.log('Execution order:', executionOrder.map(n => n.type))

    setTrainingStatus({})
    setNodes(prev => prev.map(node => ({ ...node, status: 'idle' })))

    for (const [index, node] of executionOrder.entries()) {
      setNodes(prev => prev.map(item => item.id === node.id ? { ...item, status: 'running' } : item))
      setTrainingStatus(prev => ({
        ...prev,
        [node.id]: `Step ${index + 1}/${executionOrder.length} - ${NODE_TYPES[node.type].label}`,
      }))

      try {
        const message = await executeNodeStep(node)
        setNodes(prev => prev.map(item => item.id === node.id ? { ...item, status: 'completed' } : item))
        setTrainingStatus(prev => ({ ...prev, [node.id]: message }))
      } catch (err) {
        setNodes(prev => prev.map(item => item.id === node.id ? { ...item, status: 'error' } : item))
        setTrainingStatus(prev => ({ ...prev, [node.id]: 'Step failed' }))
        setError(`Pipeline failed on ${NODE_TYPES[node.type].label}: ${err.message}`)
        break
      }
    }

    setIsTraining(false)
  }

  // Get node position for connection lines
  const getNodeCenter = (nodeId, side) => {
    const node = nodes.find(n => n.id === nodeId)
    if (!node) return { x: 0, y: 0 }
    const nodeWidth = 180
    const nodeHeight = 60

    if (side === 'output') {
      return { x: node.x + nodeWidth, y: node.y + nodeHeight / 2 }
    }
    return { x: node.x, y: node.y + nodeHeight / 2 }
  }

  // Render selected node configuration panel
  const renderConfigPanel = () => {
    if (!selectedNode) return null

    const node = nodes.find(n => n.id === selectedNode)
    if (!node) return null

    const nodeType = NODE_TYPES[node.type]

    return (
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        className="w-80 bg-dark-card border-l border-dark-border p-4 overflow-y-auto"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">{nodeType.label}</h3>
          <button
            onClick={() => setSelectedNode(null)}
            className="text-slate-400 hover:text-white"
          >
            <Icon name="x" className="w-5 h-5" />
          </button>
        </div>

        <div className="mb-4">
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-2 h-2 rounded-full ${
              node.status === 'running' ? 'bg-accent-blue animate-pulse' :
              node.status === 'completed' ? 'bg-accent-green' :
              node.status === 'error' ? 'bg-danger-red' :
              'bg-slate-500'
            }`} />
            <span className="text-sm text-slate-400">
              {trainingStatus[node.id] || 'Ready'}
            </span>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Node ID
            </label>
            <div className="text-xs text-slate-500 font-mono bg-dark-bg p-2 rounded">
              {node.id}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Description
            </label>
            <p className="text-xs text-slate-400">{nodeType.description}</p>
          </div>

          <div className="border-t border-dark-border pt-4">
            <h4 className="text-sm font-medium text-white mb-3">Parameters</h4>
            {nodeType.params.map(param => (
              <div key={param.name} className="mb-3">
                <label className="block text-xs text-slate-400 mb-1 capitalize">
                  {param.name.replace(/_/g, ' ')}
                </label>
                {param.type === 'select' ? (
                  <select
                    value={node.params[param.name]}
                    onChange={(e) => updateNodeParam(node.id, param.name, e.target.value)}
                    className="w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white"
                  >
                    {param.options.map(opt => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : param.type === 'number' ? (
                  <input
                    type="number"
                    value={node.params[param.name]}
                    onChange={(e) => updateNodeParam(node.id, param.name, parseFloat(e.target.value))}
                    className="w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white"
                  />
                ) : param.type === 'boolean' ? (
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={node.params[param.name]}
                      onChange={(e) => updateNodeParam(node.id, param.name, e.target.checked)}
                      className="w-4 h-4 rounded border-dark-border bg-dark-bg"
                    />
                    <span className="text-sm text-slate-300">
                      {node.params[param.name] ? 'Enabled' : 'Disabled'}
                    </span>
                  </label>
                ) : param.type === 'text' ? (
                  <input
                    type="text"
                    value={node.params[param.name]}
                    onChange={(e) => updateNodeParam(node.id, param.name, e.target.value)}
                    className="w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white"
                  />
                ) : param.type === 'multiselect' ? (
                  <div className="grid grid-cols-1 gap-2 rounded-lg border border-dark-border bg-dark-bg p-2">
                    {param.options.map(opt => {
                      const selectedValues = Array.isArray(node.params[param.name]) ? node.params[param.name] : []
                      const checked = selectedValues.includes(opt)

                      return (
                        <label key={opt} className="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const nextValues = e.target.checked
                                ? [...selectedValues, opt]
                                : selectedValues.filter(value => value !== opt)
                              updateNodeParam(node.id, param.name, nextValues)
                            }}
                            className="w-4 h-4 rounded border-dark-border bg-dark-bg"
                          />
                          <span>{opt}</span>
                        </label>
                      )
                    })}
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          <button
            onClick={() => deleteNode(node.id)}
            className="w-full py-2 px-4 bg-danger-red/20 border border-danger-red/40 text-danger-red rounded-lg hover:bg-danger-red/30 transition-colors text-sm"
          >
            Delete Node
          </button>
        </div>
      </motion.div>
    )
  }

  // Render metrics panel
  const renderMetricsPanel = () => {
    if (!showMetricsPanel) return null

    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="fixed bottom-4 right-4 w-96 bg-dark-card border border-dark-border rounded-xl p-4 shadow-xl z-50"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Training Metrics</h3>
          <button
            onClick={() => setShowMetricsPanel(false)}
            className="text-slate-400 hover:text-white"
          >
            <Icon name="x" className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          {['loss', 'accuracy', 'validation'].map(metric => (
            <div key={metric}>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-slate-400 capitalize">{metric}</span>
                <span className="text-white font-mono">
                  {metrics[metric].length > 0 
                    ? metrics[metric][metrics[metric].length - 1].value.toFixed(4)
                    : '-'}
                </span>
              </div>
              <div className="h-2 bg-dark-bg rounded-full overflow-hidden">
                <motion.div
                  className={`h-full ${
                    metric === 'loss' ? 'bg-danger-red' :
                    metric === 'accuracy' ? 'bg-accent-green' :
                    'bg-accent-blue'
                  }`}
                  initial={{ width: 0 }}
                  animate={{ 
                    width: `${(metrics[metric].length > 0 ? metrics[metric][metrics[metric].length - 1].value : 0) * 100}%` 
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </motion.div>
    )
  }

  return (
    <div className="min-h-screen py-8">
      <div className="max-w-full mx-auto px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6"
        >
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl md:text-4xl font-display font-bold text-white mb-2">
                ML Pipeline Builder
              </h1>
              <p className="text-slate-400">
                Build a backend-aligned PSKC pipeline with collector, trainer, registry, predictor, evaluation, and prefetch stages.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowTemplates(true)}
                className="btn-secondary flex items-center gap-2"
              >
                <Icon name="layout" className="w-4 h-4" />
                Templates
              </button>
              <label className="btn-secondary flex items-center gap-2 cursor-pointer">
                <Icon name="upload" className="w-4 h-4" />
                Import
                <input type="file" accept=".json" onChange={importPipeline} className="hidden" />
              </label>
              <button
                onClick={exportPipeline}
                className="btn-secondary flex items-center gap-2"
                disabled={nodes.length === 0}
              >
                <Icon name="download" className="w-4 h-4" />
                Export
              </button>
              <button
                onClick={runTraining}
                className="btn-primary flex items-center gap-2"
                disabled={isTraining || nodes.length === 0}
              >
                <Icon name="play" className="w-4 h-4" />
                {isTraining ? 'Training...' : 'Run Pipeline'}
              </button>
              <button
                onClick={() => setShowMetricsPanel(show => !show)}
                className="btn-secondary flex items-center gap-2"
                disabled={nodes.length === 0}
              >
                <Icon name="chart" className="w-4 h-4" />
                Metrics
              </button>
            </div>
          </div>
        </motion.div>

        {error && (
          <div className="mb-4 rounded-xl border border-danger-red/40 bg-danger-red/10 px-4 py-3 text-sm text-slate-200">
            {error}
          </div>
        )}

        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
          {BACKEND_FLOW_STAGES.map(stage => (
            <div
              key={stage.label}
              className="rounded-xl border border-dark-border bg-dark-card/80 px-4 py-3"
            >
              <div className="mb-2 flex items-center gap-3">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-lg"
                  style={{ backgroundColor: `${stage.color}20`, color: stage.color }}
                >
                  <Icon name={stage.icon} className="h-4 w-4" />
                </div>
                <div className="text-sm font-semibold text-white">{stage.label}</div>
              </div>
              <div className="text-xs text-slate-400">{stage.detail}</div>
            </div>
          ))}
        </div>

        <div className="flex gap-4">
          {/* Node Palette */}
          <div className="w-56 flex-shrink-0">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="gradient-card rounded-xl border border-dark-border p-4"
            >
              <h3 className="text-sm font-semibold text-white mb-4">Node Types</h3>
              <div className="space-y-2">
                {Object.values(NODE_TYPES).map(nodeType => (
                  <button
                    key={nodeType.id}
                    onClick={() => addNode(nodeType.id)}
                    className="w-full flex items-center gap-3 p-2 rounded-lg bg-dark-bg/50 hover:bg-dark-bg border border-transparent hover:border-dark-border transition-all text-left"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('nodeType', nodeType.id)
                    }}
                  >
                    <div 
                      className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: `${nodeType.color}20` }}
                    >
                      <Icon name={nodeType.icon} className="w-4 h-4" style={{ color: nodeType.color }} />
                    </div>
                    <span className="text-sm text-slate-300">{nodeType.label}</span>
                  </button>
                ))}
              </div>
            </motion.div>
          </div>

          {/* Canvas */}
          <div className="flex-1">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="gradient-card rounded-xl border border-dark-border overflow-hidden"
              style={{ height: 'calc(100vh - 280px)', minHeight: '500px' }}
            >
              <div
                ref={canvasRef}
                className="canvas-bg relative w-full h-full"
                onClick={handleCanvasClick}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const nodeType = e.dataTransfer.getData('nodeType')
                  if (nodeType) {
                    const rect = canvasRef.current.getBoundingClientRect()
                    addNode(nodeType, e.clientX - rect.left - 80, e.clientY - rect.top - 30)
                  }
                }}
              >
                {/* Grid background */}
                <svg className="absolute inset-0 w-full h-full pointer-events-none">
                  <defs>
                    <pattern id="pipeline-grid" width="20" height="20" patternUnits="userSpaceOnUse">
                      <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#334155" strokeWidth="0.5" opacity="0.3" />
                    </pattern>
                  </defs>
                  <rect width="100%" height="100%" fill="url(#pipeline-grid)" />
                </svg>

                {/* Connections */}
                <svg className="absolute inset-0 w-full h-full pointer-events-none">
                  {connections.map((conn, index) => {
                    const from = getNodeCenter(conn.from, 'output')
                    const to = getNodeCenter(conn.to, 'input')
                    return (
                      <g key={`${conn.from}-${conn.to}-${index}`}>
                        <line
                          x1={from.x}
                          y1={from.y}
                          x2={to.x}
                          y2={to.y}
                          stroke="#64748b"
                          strokeWidth={2}
                        />
                        <circle cx={from.x} cy={from.y} r="4" fill="#64748b" />
                        <circle cx={to.x} cy={to.y} r="4" fill="#64748b" />
                        
                        {/* Delete connection button (midpoint) */}
                        <g 
                          className="cursor-pointer hover:opacity-100 opacity-0 transition-opacity"
                          onClick={(e) => { e.stopPropagation(); deleteConnection(index); }}
                        >
                          <circle cx={(from.x + to.x)/2} cy={(from.y + to.y)/2} r="8" fill="#ef4444" />
                          <text x={(from.x + to.x)/2} y={(from.y + to.y)/2} dy="3" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">×</text>
                        </g>
                      </g>
                    )
                  })}
                  {isConnecting && connectionStart && (
                    <line
                      x1={getNodeCenter(connectionStart, 'output').x}
                      y1={getNodeCenter(connectionStart, 'output').y}
                      x2={mousePos.x}
                      y2={mousePos.y}
                      stroke="#3b82f6"
                      strokeWidth={2}
                      strokeDasharray="5,5"
                    />
                  )}
                </svg>

                {/* Nodes */}
                {nodes.map(node => {
                  const nodeType = NODE_TYPES[node.type]
                  const isSelected = selectedNode === node.id
                  const isHovered = hoveredNode === node.id
                  
                  return (
                    <motion.div
                      key={node.id}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1, x: node.x, y: node.y }}
                      className={`absolute select-none ${draggedNode === node.id ? 'z-50 cursor-grabbing' : 'cursor-grab'}`}
                      style={{ 
                        width: 180, 
                        height: 60,
                      }}
                      onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                      onMouseEnter={() => handleNodeMouseEnter(node.id)}
                      onMouseLeave={handleNodeMouseLeave}
                    >
                      <div 
                        className={`w-full h-full rounded-xl border-2 flex items-center gap-3 px-3 transition-all ${
                          isSelected 
                            ? 'border-accent-blue shadow-lg shadow-accent-blue/20' 
                            : 'border-dark-border hover:border-slate-600'
                        }`}
                        style={{ 
                          backgroundColor: `${nodeType.color}15`,
                        }}
                      >
                        <div 
                          className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: `${nodeType.color}30` }}
                        >
                          <Icon name={nodeType.icon} className="w-5 h-5" style={{ color: nodeType.color }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-white truncate">{nodeType.label}</div>
                          <div className="flex items-center gap-1">
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              node.status === 'running' ? 'bg-accent-blue animate-pulse' :
                              node.status === 'completed' ? 'bg-accent-green' :
                              node.status === 'error' ? 'bg-danger-red' :
                              'bg-slate-500'
                            }`} />
                            <span className="text-xs text-slate-400 truncate">
                              {trainingStatus[node.id] || 'Ready'}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Connection points */}
                      {/* Input point (LEFT) - target for connections */}
                      <div
                        className={`absolute -left-4 top-1/2 -translate-y-1/2 w-8 h-8 bg-dark-bg border-2 rounded-full cursor-pointer flex items-center justify-center transition-all z-20 ${isHovered && isConnecting ? 'border-accent-green bg-accent-green/40' : 'border-accent-green/50 hover:border-accent-green hover:bg-accent-green/20'}`}
                        onMouseEnter={() => handleNodeMouseEnter(node.id)}
                        onMouseLeave={handleNodeMouseLeave}
                        title="Input Point"
                      >
                        <div className={`w-3 h-3 rounded-full ${isHovered && isConnecting ? 'bg-accent-green' : 'bg-accent-green/50'}`} />
                      </div>

                      {/* Output point (RIGHT) - drag from here to connect */}
                      <div
                        className="absolute -right-4 top-1/2 -translate-y-1/2 w-8 h-8 bg-dark-bg border-2 border-accent-blue rounded-full cursor-crosshair hover:bg-accent-blue/40 flex items-center justify-center transition-all z-50"
                        onMouseDown={(e) => handleConnectionStart(e, node.id)}
                        title="Output Point (Drag to connect)"
                      >
                        <div className="w-3 h-3 bg-accent-blue rounded-full" />
                      </div>
                    </motion.div>
                  )
                })}

                {/* Empty state with instructions */}
                {nodes.length === 0 && (
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div className="text-center">
                      <Icon name="layers" className="w-16 h-16 text-slate-600 mx-auto mb-4" />
                      <p className="text-slate-400 text-lg mb-2">Drag nodes from the left palette</p>
                      <p className="text-slate-500 text-sm mb-4">or start from a backend-aligned template</p>
                      <div className="flex flex-wrap gap-2 justify-center pointer-events-auto">
                        {['pskc_runtime', 'prediction_feedback', 'classification', 'regression'].map(templateKey => {
                          const template = TEMPLATES[templateKey]
                          return (
                            <button
                              key={templateKey}
                              onClick={() => loadTemplate(templateKey)}
                              className="rounded-lg border px-4 py-2 text-sm transition-colors"
                              style={{
                                backgroundColor: `${template.accent || '#3b82f6'}20`,
                                borderColor: `${template.accent || '#3b82f6'}66`,
                                color: template.accent || '#3b82f6',
                              }}
                            >
                              {template.name}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          </div>

          {/* Configuration Panel */}
          <AnimatePresence>
            {selectedNode && renderConfigPanel()}
          </AnimatePresence>
        </div>

        {/* Templates Modal */}
        <AnimatePresence>
          {showTemplates && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50"
              onClick={() => setShowTemplates(false)}
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                className="bg-dark-card border border-dark-border rounded-2xl p-6 max-w-4xl w-full mx-4"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xl font-semibold text-white">Pipeline Templates</h2>
                  <button
                    onClick={() => setShowTemplates(false)}
                    className="text-slate-400 hover:text-white"
                  >
                    <Icon name="x" className="w-5 h-5" />
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {Object.entries(TEMPLATES).map(([key, template]) => (
                    <button
                      key={key}
                      onClick={() => loadTemplate(key)}
                      className="p-4 rounded-xl bg-dark-bg border border-dark-border hover:border-accent-blue transition-colors text-left"
                    >
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div
                          className="w-10 h-10 rounded-lg flex items-center justify-center"
                          style={{ backgroundColor: `${template.accent || '#3b82f6'}20`, color: template.accent || '#3b82f6' }}
                        >
                          <Icon name={template.icon || 'grid'} className="w-5 h-5" />
                        </div>
                        {template.recommended && (
                          <span className="rounded-full border border-accent-green/40 bg-accent-green/15 px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-accent-green">
                            Recommended
                          </span>
                        )}
                      </div>
                      <h3 className="font-semibold text-white mb-1">{template.name}</h3>
                      <p className="text-xs text-slate-400">{template.description}</p>
                      <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                        {template.nodes.length} nodes • {template.connections.length} connections
                      </div>
                    </button>
                  ))}
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Metrics Panel */}
        <AnimatePresence>
          {renderMetricsPanel()}
        </AnimatePresence>
      </div>
    </div>
  )
}

export default MLPipelineBuilder
