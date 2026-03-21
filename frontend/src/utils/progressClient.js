/**
 * WebSocket Client for Real-time Training Progress Tracking
 * 
 * Usage:
 * const client = new TrainingProgressWebSocket('localhost:8000');
 * client.onUpdate((update) => console.log(update));
 * client.connect();
 * 
 * Update Structure:
 * {
 *   phase: "training_lstm",
 *   progress_percent: 45.5,
 *   current_step: 15,
 *   total_steps: 50,
 *   message: "Epoch 15/50",
 *   timestamp: "2024-01-02T12:00:00Z",
 *   details: { train_accuracy: 0.78, ... }
 * }
 */

export class TrainingProgressWebSocket {
  constructor(serverUrl = 'localhost:8000') {
    this.serverUrl = serverUrl;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 1000; // ms
    this.callbacks = [];
    this.isConnecting = false;
  }

  /**
   * Register callback for progress updates
   */
  onUpdate(callback) {
    if (typeof callback === 'function') {
      this.callbacks.push(callback);
    }
    return this;
  }

  /**
   * Remove callback
   */
  offUpdate(callback) {
    this.callbacks = this.callbacks.filter(cb => cb !== callback);
    return this;
  }

  /**
   * Connect to WebSocket
   */
  connect() {
    if (this.isConnecting || this.ws) {
      console.warn('WebSocket already connecting or connected');
      return;
    }

    this.isConnecting = true;

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${protocol}://${this.serverUrl}/ml/training/progress/stream`;
      
      console.log(`Connecting to training progress WebSocket: ${url}`);
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        console.log('Training progress WebSocket connected');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
      };

      this.ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);
          this._notifyCallbacks(update);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error, event.data);
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.isConnecting = false;
      };

      this.ws.onclose = () => {
        console.log('Training progress WebSocket disconnected');
        this.ws = null;
        this.isConnecting = false;
        this._attemptReconnect();
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.isConnecting = false;
      this._attemptReconnect();
    }
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  _attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);

    setTimeout(() => {
      this.connect();
    }, delay);
  }

  /**
   * Disconnect WebSocket
   */
  disconnect() {
    this.reconnectAttempts = this.maxReconnectAttempts; // Prevent reconnection
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    console.log('Training progress WebSocket disconnected');
  }

  /**
   * Check if connected
   */
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Notify all callbacks of update
   */
  _notifyCallbacks(update) {
    this.callbacks.forEach(callback => {
      try {
        callback(update);
      } catch (error) {
        console.error('Callback error:', error);
      }
    });
  }
}

/**
 * WebSocket Client for Data Generation Progress
 */
export class DataGenerationProgressWebSocket {
  constructor(serverUrl = 'localhost:8000') {
    this.serverUrl = serverUrl;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 1000; // ms
    this.callbacks = [];
    this.isConnecting = false;
  }

  /**
   * Register callback for progress updates
   */
  onUpdate(callback) {
    if (typeof callback === 'function') {
      this.callbacks.push(callback);
    }
    return this;
  }

  /**
   * Remove callback
   */
  offUpdate(callback) {
    this.callbacks = this.callbacks.filter(cb => cb !== callback);
    return this;
  }

  /**
   * Connect to WebSocket
   */
  connect() {
    if (this.isConnecting || this.ws) {
      console.warn('WebSocket already connecting or connected');
      return;
    }

    this.isConnecting = true;

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${protocol}://${this.serverUrl}/ml/training/generate-progress/stream`;
      
      console.log(`Connecting to data generation progress WebSocket: ${url}`);
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        console.log('Data generation progress WebSocket connected');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
      };

      this.ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);
          this._notifyCallbacks(update);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error, event.data);
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.isConnecting = false;
      };

      this.ws.onclose = () => {
        console.log('Data generation progress WebSocket disconnected');
        this.ws = null;
        this.isConnecting = false;
        this._attemptReconnect();
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.isConnecting = false;
      this._attemptReconnect();
    }
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  _attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);

    setTimeout(() => {
      this.connect();
    }, delay);
  }

  /**
   * Disconnect WebSocket
   */
  disconnect() {
    this.reconnectAttempts = this.maxReconnectAttempts; // Prevent reconnection
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    console.log('Data generation progress WebSocket disconnected');
  }

  /**
   * Check if connected
   */
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Notify all callbacks of update
   */
  _notifyCallbacks(update) {
    this.callbacks.forEach(callback => {
      try {
        callback(update);
      } catch (error) {
        console.error('Callback error:', error);
      }
    });
  }
}

/**
 * Polling fallback for browsers that don't support WebSocket
 * or as an alternative to WebSocket
 */
export class TrainingProgressPoller {
  constructor(apiUrl = 'http://localhost:8000', pollInterval = 1000) {
    this.apiUrl = apiUrl;
    this.pollInterval = pollInterval;
    this.pollingTimer = null;
    this.callbacks = [];
    this.lastUpdate = null;
  }

  /**
   * Register callback for progress updates
   */
  onUpdate(callback) {
    if (typeof callback === 'function') {
      this.callbacks.push(callback);
    }
    return this;
  }

  /**
   * Remove callback
   */
  offUpdate(callback) {
    this.callbacks = this.callbacks.filter(cb => cb !== callback);
    return this;
  }

  /**
   * Start polling
   */
  start() {
    if (this.pollingTimer) {
      console.warn('Polling already started');
      return;
    }

    console.log(`Starting training progress polling every ${this.pollInterval}ms`);
    this._poll();
  }

  /**
   * Stop polling
   */
  stop() {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer);
      this.pollingTimer = null;
    }
    console.log('Training progress polling stopped');
  }

  /**
   * Poll for updates
   */
  _poll() {
    const poll = async () => {
      try {
        const response = await fetch(`${this.apiUrl}/ml/training/progress`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const update = await response.json();
        
        // Only notify if changed
        if (JSON.stringify(update) !== JSON.stringify(this.lastUpdate)) {
          this.lastUpdate = update;
          this._notifyCallbacks(update);
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    };

    // Initial poll
    poll();
    
    // Set up interval
    this.pollingTimer = setInterval(poll, this.pollInterval);
  }

  /**
   * Notify all callbacks of update
   */
  _notifyCallbacks(update) {
    this.callbacks.forEach(callback => {
      try {
        callback(update);
      } catch (error) {
        console.error('Callback error:', error);
      }
    });
  }
}

/**
 * Data Generation Poller (fallback for WebSocket)
 */
export class DataGenerationProgressPoller {
  constructor(apiUrl = 'http://localhost:8000', pollInterval = 1000) {
    this.apiUrl = apiUrl;
    this.pollInterval = pollInterval;
    this.pollingTimer = null;
    this.callbacks = [];
    this.lastUpdate = null;
  }

  /**
   * Register callback for progress updates
   */
  onUpdate(callback) {
    if (typeof callback === 'function') {
      this.callbacks.push(callback);
    }
    return this;
  }

  /**
   * Remove callback
   */
  offUpdate(callback) {
    this.callbacks = this.callbacks.filter(cb => cb !== callback);
    return this;
  }

  /**
   * Start polling
   */
  start() {
    if (this.pollingTimer) {
      console.warn('Polling already started');
      return;
    }

    console.log(`Starting data generation polling every ${this.pollInterval}ms`);
    this._poll();
  }

  /**
   * Stop polling
   */
  stop() {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer);
      this.pollingTimer = null;
    }
    console.log('Data generation polling stopped');
  }

  /**
   * Poll for updates
   */
  _poll() {
    const poll = async () => {
      try {
        const response = await fetch(`${this.apiUrl}/ml/training/generate-progress`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const update = await response.json();
        
        // Only notify if changed
        if (JSON.stringify(update) !== JSON.stringify(this.lastUpdate)) {
          this.lastUpdate = update;
          this._notifyCallbacks(update);
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    };

    // Initial poll
    poll();
    
    // Set up interval
    this.pollingTimer = setInterval(poll, this.pollInterval);
  }

  /**
   * Notify all callbacks of update
   */
  _notifyCallbacks(update) {
    this.callbacks.forEach(callback => {
      try {
        callback(update);
      } catch (error) {
        console.error('Callback error:', error);
      }
    });
  }
}
