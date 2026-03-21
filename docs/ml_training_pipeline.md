# ML Model Training Pipeline

Dokumen ini menjelaskan complete training pipeline dari data collection sampai model deployment, termasuk drift detection dan model lifecycle.

## Ikhtisar

ML training pipeline adalah backbone yang membuat PSKC dapat memprediksi akses kunci dan mengoptimalkan caching. Pipeline terdiri dari 3 tahap utama:

```
┌──────────────────────────────────────────────────────────┐
│              ML TRAINING PIPELINE OVERVIEW              │
└──────────────────────────────────────────────────────────┘

RUNTIME PHASE (Production):
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Client    │────▶│  PSKC API Server │────▶│    KMS      │
│  requests   │     │   (online)       │     │  (upstream) │
└─────────────┘     └────────┬──────────┘     └─────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
        ┌───────▼────────┐      ┌─────────▼─────────┐
        │ Cache Layer    │      │ Data Collector    │
        │ (L1+L2)        │      │ (background)      │
        └────────────────┘      └─────────┬─────────┘
                                          │
                                  ┌───────▼──────────┐
                                  │ Historical Stats │
                                  │ in Redis         │
                                  └──────────────────┘

TRAINING PHASE (Batch, every 6 hours):
┌───────────────────────────────┐
│  Trainer (triggered batch job)│
│  1. Load historical stats     │
│  2. Extract features          │
│  3. Train ensemble model      │
│  4. Run drift detection       │
│  5. Deploy if improved        │
└──────────┬────────────────────┘
           │
  ┌────────▼──────────┐
  │  Model Registry   │ ────▶ Model artifacts on disk
  │  (versioning)     │ ────▶ Signature + checksum
  └─────────┬─────────┘
            │
   ┌────────▼──────────┐
   │ API Server reload │
   │ (detect new model)│
   └───────────────────┘
```

---

## Stage 1: Data Collection (Online)

### DataCollector Component

**File**: `src/ml/data_collector.py`

**Responsibility**: Aggregate key access patterns in real-time

### Collection Events

Every time a key is accessed, DataCollector records:

```python
# Event structure (stored in Redis)
access_event = {
    "timestamp": 1711003260.123,           # Unix time
    "key_id": "user_123:key_456",
    "service_id": "api-prod",
    "access_type": "read",                 # or "write"
    "cache_hit": True,                     # Was it in cache?
    "latency_ms": 2.5,                     # Response time
    "client_ip": "10.0.1.5",
    "feature_context": {
        "is_burst": False,
        "time_since_last_access_ms": 45000,
        "daily_access_count": 342
    }
}

# Implementation:
data_collector.record_access(
    key_id="user_123:key_456",
    service_id="api-prod",
    access_type="read",
    cache_hit=was_cache_hit,
    latency_ms=elapsed_ms,
    client_ip=client_ip
)
```

### Storage in Redis

```
Redis Structure:

HASH: pskc:data:access_sequences:{service_id}
  Field: {key_id}
  Value: JSON list of recent accesses
  
Example:
  key: pskc:data:access_sequences:api-prod
  value: 
    user_123:key_456 → [
      {ts: 1711003200, hit: true, lat: 2.5},
      {ts: 1711003145, hit: false, lat: 120},
      {ts: 1711003090, hit: true, lat: 2.8},
      ... last 1000 accesses or 24 hours ...
    ]

Cleanup:
  TTL: 24 hours (auto-expire unused keys)
  Size limit: Keep last 1000 accesses per key
  When over limit: Remove oldest entries
```

### Configuration

```env
# Data Collection Settings
ML_COLLECTOR_ENABLED=true
ML_COLLECTOR_HISTORICAL_STATS_TTL_SECONDS=604800          # 7 days
ML_COLLECTOR_HISTORICAL_STATS_MAX_ENTRIES=10000           # Per key
ML_COLLECTOR_BATCH_SIZE=100                               # Events per batch

# Feature Extraction Settings
ML_FEATURE_BURST_THRESHOLD_SECONDS=1.0                    # Define "burst"
ML_FEATURE_REGULAR_RANGE_SECONDS="10,60"                  # Regular access range
ML_FEATURE_IDLE_THRESHOLD_SECONDS=3600                    # When key is idle
```

---

## Stage 2: Feature Engineering (Online → Batch)

### FeatureEngineer Component

**File**: `src/ml/feature_engineering.py`

**Responsibility**: Convert raw access events into ML-ready feature vectors

### Feature Categories

```
TEMPORAL FEATURES (8 dimensions):
├─ time_of_day_hour: 0-23
├─ day_of_week: 0-6
├─ is_business_hours: binary (0-1)
├─ time_since_last_access: minutes (capped at 1440)
├─ access_frequency_1h: count
├─ access_frequency_24h: count
├─ days_since_creation: capped at 365
└─ recency_score: normalized 0-1

PATTERN FEATURES (6 dimensions):
├─ is_burst_pattern: binary
├─ burst_intensity: 0-1 (if burst)
├─ access_type_entropy: normalized 0-1
├─ service_diversity: count of different services
├─ followed_by_key_count: how many different keys typically follow
└─ next_access_prediction_entropy: 0-1

SERVICE FEATURES (4 dimensions):
├─ primary_service_frequency: 0-1
├─ multi_service_access_ratio: 0-1
├─ service_change_count_24h: count
└─ service_consistency_score: 0-1

LATENCY FEATURES (6 dimensions):
├─ avg_latency_ms: last 100 accesses
├─ p50_latency_ms: median
├─ p95_latency_ms: 95th percentile
├─ p99_latency_ms: 99th percentile
├─ latency_variance: standard deviation
└─ cache_hit_rate_24h: hit_count / total_count

FREQUENCY FEATURES (6 dimensions):
├─ access_rate_per_minute: current rate
├─ access_volatility: coefficient of variation
├─ trend_direction: increasing / stable / decreasing
├─ seasonality_detected: binary
├─ total_accesses_lifetime: log-normalized
└─ inactive_period_days: if idle > threshold

TOTAL: 30 dimensions
```

### Feature Extraction Process

```python
# Called before training and during prefetch prediction

features = feature_engineer.extract_features(
    key_id="user_123:key_456",
    service_id="api-prod",
    window_seconds=300  # Last 5 minutes context
)

# Output: numpy array shape (30,)
# Example:
# [
#   14.0,          # 2 PM (hour)
#   2.0,           # Tuesday
#   1.0,           # Business hours
#   45.2,          # Minutes since last access
#   ...
#   0.92,          # Cache hit rate
# ]

# Validation:
assert features.shape == (30,), f"Expected 30 features, got {features.shape[0]}"
```

### Feature Normalization

```
Most features normalized to [0, 1] range:

Examples:
  time_of_day_hour / 24              → 0-1 (14 → 0.583)
  access_frequencies / max(100, X)   → 0-1 (capped at reasonable max)
  latency_ms / 1000                  → 0-1 (capped)
  
Exceptions (raw values):
  day_of_week: 0-6 (not normalized)
  Counts: 0-N (not normalized)
  
Benefit:
  Neural networks (LSTM) train better with normalized features
  Prevents large values from dominating gradients
```

---

## Stage 3A: Training Data Preparation

### Data Aggregation

```python
# Trainer runs batch job (every 6 hours):

def prepare_training_data():
    """Aggregate access patterns into supervised learning dataset"""
    
    # Load all historical data from Redis
    historical_data = data_collector.get_all_historical_stats()
    # Shape: dict of {key_id: [access1, access2, ...]}
    
    # For each key, extract features from time window
    # Then label: "what key was accessed next?"
    
    training_samples = []
    
    for service_id, keys_data in historical_data.items():
        for key_id, access_sequence in keys_data.items():
            # access_sequence: [
            #   {ts: 1700000000, ...},
            #   {ts: 1700000100, ...},
            #   {ts: 1700000200, ...},  ← target
            # ]
            
            for i in range(len(access_sequence) - 1):
                # Use accesses [0:i] to predict access[i]
                context_accesses = access_sequence[:i]
                target_access = access_sequence[i]
                next_access = access_sequence[i+1]
                
                # Extract features from context
                features = feature_engineer.extract_features(
                    key_id=key_id,
                    access_history=context_accesses
                )
                
                # Label: next key accessed after target
                label = next_access['next_key_id']
                
                training_samples.append({
                    'features': features,
                    'target_key': key_id,
                    'label': label,
                    'weight': compute_sample_weight(key_id)
                })
    
    return training_samples

# Dataset characteristics:
# - Size: 10,000 - 100,000 samples (depends on traffic)
# - Features: 30 dimensions per sample
# - Labels: 1,000 - 10,000 unique keys (depends on diversity)
# - Time period: Last 7 days of access history
```

### Balancing for Class Imbalance

```python
def compute_sample_weight(key_id):
    """
    Popular keys appear more often → weight down
    Rare keys appear less → weight up
    
    Ensures model learns patterns for ALL keys, not just popular ones
    """
    frequency = access_frequency[key_id]  # 1-1000
    
    if frequency > 100:
        weight = 0.5  # Down-weight popular
    elif frequency > 10:
        weight = 1.0  # Normal
    else:
        weight = 2.0  # Up-weight rare keys
    
    return weight

# Applied in training:
model.fit(X_train, y_train, sample_weight=weights)
```

---

## Stage 3B: Model Training

### Trainer Component

**File**: `src/ml/model.py` → `Trainer` class

### Training Components

The ensemble model consists of 3 sub-models:

#### 1. LSTM Model (Sequence Predictor)

```python
# Captures temporal patterns in access sequences

class LSTMModel:
    def __init__(self, config):
        self.input_size = config.ml_lstm_input_size           # 30
        self.hidden_size = config.ml_lstm_hidden_size         # 64
        self.num_layers = config.ml_lstm_num_layers           # 2
        self.output_size = config.ml_lstm_output_size         # 5000 keys
        
        self.lstm = torch.nn.LSTM(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=0.2,
            batch_first=True
        )
        
        self.fc = torch.nn.Linear(self.hidden_size, self.output_size)
    
    def forward(self, x):
        # x shape: (batch_size, seq_len, 30)
        lstm_out, _ = self.lstm(x)          # (batch, seq, 64)
        logits = self.fc(lstm_out[:, -1, :]) # (batch, 5000)
        return logits
```

**Training Process**:
```python
def train_lstm(X_train, y_train, config):
    """
    X_train: shape (N_samples, 10, 30)  # 10-step sequences of 30-dim features
    y_train: shape (N_samples,)          # Key indices to predict (0-5000)
    """
    
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=config.ml_lstm_learning_rate  # 0.001
    )
    
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode='min',
        factor=0.5,
        patience=config.ml_lstm_lr_schedule_patience  # 5
    )
    
    loss_fn = torch.nn.CrossEntropyLoss(
        weight=class_weights  # Balance for rare keys
    )
    
    best_val_loss = float('inf')
    patience = config.ml_lstm_early_stopping_patience  # 10
    no_improve_count = 0
    
    for epoch in range(config.ml_lstm_max_epochs):  # Max 50
        # Training loop
        for batch in train_loader:
            optimizer.zero_grad()
            logits = model(batch['features'])
            loss = loss_fn(logits, batch['labels'])
            loss.backward()
            optimizer.step()
        
        # Validation
        val_loss = evaluate_on_validation_set()
        
        # Early stopping
        if val_loss < best_val_loss - config.ml_lstm_early_stopping_min_delta:
            best_val_loss = val_loss
            no_improve_count = 0
            save_checkpoint(model)  # Save best model
        else:
            no_improve_count += 1
        
        # Learning rate scheduling
        scheduler.step(val_loss)
        
        # Early stopping trigger
        if no_improve_count >= patience:
            logger.info(f"Early stopping at epoch {epoch}")
            break
        
        logger.info(f"Epoch {epoch}: val_loss={val_loss:.4f}")
    
    load_checkpoint(model)  # Load best checkpoint
    return model
```

**How it predicts**:
```python
def predict_next_key_lstm(current_features_sequence):
    """
    current_features_sequence: Last 10 accesses, shape (10, 30)
    """
    with torch.no_grad():
        logits = model(current_features_sequence.unsqueeze(0))
        # logits shape: (1, 5000)
        
        probabilities = torch.softmax(logits, dim=1)
        top_k_indices = torch.topk(probabilities, k=10)[1]
        # Returns indices of top 10 most likely next keys
    
    return predicted_keys, confidence_scores
```

#### 2. RandomForest Model (Feature Importance)

```python
# Captures non-linear relationships between individual features

class RandomForestModel:
    def __init__(self, config):
        self.model = RandomForestClassifier(
            n_estimators=config.ml_rf_n_estimators,               # 100
            max_depth=config.ml_rf_max_depth,                     # 15
            min_samples_split=config.ml_rf_min_samples_split,     # 5
            min_samples_leaf=config.ml_rf_min_samples_leaf,       # 2
            max_features=config.ml_rf_max_features,               # 'sqrt'
            class_weight='balanced',                              # Handle imbalance
            n_jobs=-1,                                            # Use all cores
            random_state=42
        )
    
    def train(self, X_train, y_train, sample_weight=None):
        self.model.fit(X_train, y_train, sample_weight=sample_weight)
    
    def get_feature_importances(self):
        """Return importance scores for each of 30 features"""
        return self.model.feature_importances_  # shape (30,)
    
    def log_feature_importances(self, feature_names):
        importances = self.get_feature_importances()
        for name, importance in zip(feature_names, importances):
            logger.info(f"Feature {name}: importance={importance:.4f}")
```

**How it predicts**:
```python
def predict_next_key_rf(features):
    """
    features: shape (30,) for single sample
    
    RandomForest processes each feature independently:
    - "Has burst pattern?" → suggests certain keys
    - "High latency P99?" → suggests different access pattern
    - "Idle for 3600s?" → suggests expiration check
    """
    probabilities = model.predict_proba(features.reshape(1, -1))
    # Returns probability distribution over all possible next keys
    
    return predicted_keys, confidence_scores
```

#### 3. Markov Chain Model (Lightweight)

```python
# Captures most common transitions (lightweight, no training needed)

class MarkovChainPredictor:
    def __init__(self, config):
        self.transition_counts = {}  # key_pair -> count
        self.max_transitions = config.ml_markov_max_transitions  # 100,000
        self.smoothing = config.ml_markov_smoothing              # 0.1
    
    def build_from_data(self, access_sequences):
        """
        access_sequences: [
          {ts: 1700000000, key: 'user_123:key_456'},
          {ts: 1700000100, key: 'user_123:key_789'},  ← transition!
          ...
        ]
        """
        for i in range(len(access_sequences) - 1):
            current_key = access_sequences[i]['key']
            next_key = access_sequences[i+1]['key']
            pair = (current_key, next_key)
            
            self.transition_counts[pair] = self.transition_counts.get(pair, 0) + 1
        
        # Prune if too many transitions
        if len(self.transition_counts) > self.max_transitions:
            self._prune_transitions()
    
    def _prune_transitions(self):
        """Keep only most frequent transitions"""
        sorted_pairs = sorted(
            self.transition_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Keep top 80% by frequency
        keep_count = int(0.8 * self.max_transitions)
        self.transition_counts = dict(sorted_pairs[:keep_count])
    
    def predict(self, current_key):
        """Return likely next keys"""
        # Get all (current_key, X) transitions
        transitions = [
            (pair[1], count)
            for pair, count in self.transition_counts.items()
            if pair[0] == current_key
        ]
        
        # Normalize with Laplace smoothing
        total = sum(count for _, count in transitions) + self.smoothing
        
        return sorted(
            [(key, (count + self.smoothing) / total) for key, count in transitions],
            key=lambda x: x[1],
            reverse=True
        )[:10]
```

### Ensemble Voting

```python
class EnsembleModel:
    """Combine 3 models into single prediction"""
    
    def __init__(self, lstm_model, rf_model, markov_model):
        self.lstm = lstm_model
        self.rf = rf_model
        self.markov = markov_model
    
    def predict_top_n(self, features, n=10):
        """
        features: shape (10, 30) for LSTM or (30,) for RF/Markov
        """
        predictions = [
            self.lstm.predict(features),      # (key_id, prob)
            self.rf.predict(features),
            self.markov.predict(current_key)
        ]
        
        # Ensemble: weighted average of probabilities
        weights = self.get_dynamic_weights()  # (w_lstm, w_rf, w_markov)
        
        final_scores = {}
        for i, (model_preds, weight) in enumerate(zip(predictions, weights)):
            for key_id, prob in model_preds:
                final_scores[key_id] = final_scores.get(key_id, 0) + weight * prob
        
        # Sort by score and return top N
        sorted_preds = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_preds[:n]
    
    def get_dynamic_weights(self):
        """Weight models based on recent accuracy"""
        # Tracked in EnsembleWeightTracker
        # Example: LSTM 0.5, RF 0.3, Markov 0.2
        return self.weight_tracker.get_current_weights()
```

---

## Stage 4: Drift Detection

### Concept Drift

**Problem**: Access patterns change over time
- New keys introduced
- Usage patterns shift (e.g., burst → regular)
- Model accuracy degrades

**Detection Algorithms**:

#### EWMA (Exponentially Weighted Moving Average)

```python
class DriftDetectorEWMA:
    """
    Simple rolling average, recent data weighted more
    """
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.mean = 0
    
    def update(self, accuracy):
        """Track model accuracy over time"""
        self.mean = self.alpha * accuracy + (1 - self.alpha) * self.mean
        return self.mean
    
    def detect_drift(self, current_accuracy, threshold=0.02):
        """
        If current_accuracy < mean - threshold → drift detected
        """
        drift_detected = current_accuracy < (self.mean - threshold)
        return drift_detected
```

#### ADWIN (Adaptive Windowing)

```python
class DriftDetectorADWIN:
    """
    More sophisticated: maintains window of recent observations
    Detects abrupt changes
    """
    def __init__(self, delta=0.002):
        self.delta = delta
        self.window = []
        self.width = 0
    
    def add_element(self, accuracy):
        """Add new observation"""
        self.window.append(accuracy)
        self.width = len(self.window)
        
        # Check for concept change
        drift = self._detect_change()
        
        if drift:
            # Reset window
            self.window = [accuracy]
            self.width = 1
        
        return drift
    
    def _detect_change(self):
        """Compare first half vs second half of window"""
        if len(self.window) < 10:
            return False
        
        mid = len(self.window) // 2
        first_half_acc = sum(self.window[:mid]) / mid
        second_half_acc = sum(self.window[mid:]) / len(self.window[mid:])
        
        # If second half significantly different → drift
        drift_detected = abs(second_half_acc - first_half_acc) > 0.05
        
        return drift_detected
```

### Drift Monitoring During Training

```python
def train_with_drift_detection(trainer_config):
    """Train new model and check if better than current"""
    
    # Split: 70% train, 30% validation
    train_set, val_set = split_data(all_data, ratio=0.7)
    
    # Train LSTM, RF, Markov independently
    lstm_new = train_lstm(train_set)
    rf_new = train_rf(train_set)
    markov_new = build_markov(train_set)
    
    ensemble_new = EnsembleModel(lstm_new, rf_new, markov_new)
    
    # Evaluate on validation set
    new_accuracy = evaluate_ensemble(ensemble_new, val_set)
    
    # Get current model accuracy (on same validation set)
    ensemble_current = load_active_model()
    current_accuracy = evaluate_ensemble(ensemble_current, val_set)
    
    # Drift detection
    drift_detector.update(new_accuracy)
    drift_detected = drift_detector.detect_drift(new_accuracy)
    
    if drift_detected:
        logger.warning(f"Concept drift detected!")
        logger.warning(f"Current accuracy: {current_accuracy:.4f}")
        logger.warning(f"New model accuracy: {new_accuracy:.4f}")
        # Trigger retraining with more data or different hyperparameters
    
    # Model improvement check
    improvement = new_accuracy - current_accuracy
    
    if improvement > 0.01:  # 1% minimum improvement
        logger.info(f"Model improved: {improvement:.4f}")
        save_and_deploy(ensemble_new)
    else:
        logger.info(f"No significant improvement: {improvement:.4f}")
        # Keep using current model
```

---

## Stage 5: Model Deployment

### Model Registry

**File**: `src/ml/model_registry.py`

```python
class ModelRegistry:
    """Manages model versions, checksums, signatures"""
    
    def save_model(self, model_data, artifact_type='ensemble'):
        """
        1. Serialize ensemble (LSTM + RF + Markov)
        2. Compute checksum
        3. Sign with private key
        4. Store metadata
        """
        
        # Serialize
        model_bytes = pickle.dumps(model_data)
        
        # Checksum (for integrity)
        checksum = hashlib.sha256(model_bytes).hexdigest()
        
        # Sign (for authenticity + non-repudiation)
        signature = self.fips_module.sign_data(model_bytes)
        
        # Save to disk
        model_path = f"data/models/{artifact_type}_v{version}.pskc"
        with open(model_path, 'wb') as f:
            f.write(model_bytes)
        
        # Save metadata
        metadata = {
            'artifact_type': artifact_type,
            'version': version,
            'created_at': datetime.utcnow().isoformat(),
            'checksum': checksum,
            'signature': signature.hex(),
            'model_class': model_data.__class__.__name__,
            'hyperparameters': {
                'lstm_hidden_size': model_data.lstm.hidden_size,
                'rf_n_estimators': model_data.rf.n_estimators,
                'markov_max_transitions': model_data.markov.max_transitions
            }
        }
        
        metadata_path = f"data/models/{artifact_type}_v{version}.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f)
        
        return model_path, metadata_path
    
    def load_model(self, artifact_type='ensemble', version=None):
        """
        1. Find latest version
        2. Verify checksum
        3. Verify signature
        4. Deserialize
        """
        
        if version is None:
            # Load latest
            latest_version = self.get_latest_version(artifact_type)
            model_path = f"data/models/{artifact_type}_v{latest_version}.pskc"
        else:
            model_path = f"data/models/{artifact_type}_v{version}.pskc"
        
        # Load metadata
        metadata_path = model_path.replace('.pskc', '.json')
        with open(metadata_path) as f:
            metadata = json.load(f)
        
        # Load model bytes
        with open(model_path, 'rb') as f:
            model_bytes = f.read()
        
        # Verify checksum
        computed_checksum = hashlib.sha256(model_bytes).hexdigest()
        if computed_checksum != metadata['checksum']:
            raise ValueError(f"Checksum mismatch for {artifact_type}")
        
        # Verify signature
        if not self.fips_module.verify_signature(model_bytes, metadata['signature']):
            raise SecurityError(f"Signature verification failed for {artifact_type}")
        
        # Deserialize
        model = pickle.loads(model_bytes)
        model.is_trained = True
        
        return model
```

### Active Model Detection

```python
# In API server initialization:

def load_active_ensemble_model():
    """
    Read model registry, check for new version
    """
    
    try:
        # Try to load latest
        ensemble = model_registry.load_model('ensemble')
        
        # Verify it's trained
        if not ensemble.is_trained:
            logger.error("Model not trained, using fallback")
            return ensemble  # Will use fallback Markov
        
        logger.info(f"Loaded ensemble model: v{ensemble.version}")
        return ensemble
        
    except Exception as e:
        logger.error(f"Failed to load ensemble: {e}")
        # Fallback to lightweight Markov
        return create_fallback_markov_model()
```

### Model Versioning

```
Versions stored as:
  data/models/ensemble_v1.pskc         # v1: Initial model
  data/models/ensemble_v2.pskc         # v2: Retrained with more data
  data/models/ensemble_v3.pskc         # v3: After drift detected
  etc.

Latest tracked in:
  data/models/checksums.json
  {
    "ensemble": {
      "latest_version": 3,
      "checksum": "sha256:xxxxx",
      "created_at": "2024-03-20T16:00:00Z"
    }
  }
```

---

## Complete Training Cycle

### Trigger: Scheduled (Every 6 Hours)

```bash
# In Kubernetes CronJob or systemd timer:
0 */6 * * * python -m src.ml.trainer

# Or in docker-compose:
services:
  trainer:
    image: pskc:latest
    entrypoint: |
      /bin/bash -c "while true; do
        sleep 21600;  # 6 hours
        python -m src.ml.trainer;
      done"
```

### Full Training Workflow

```python
def main_training_loop():
    config = load_config()
    
    # 1. Load access history from Redis
    logger.info("Loading access history...")
    historical_data = data_collector.get_all_historical_stats()
    # Last 7 days of all access events
    
    # 2. Prepare training dataset
    logger.info("Preparing training data...")
    training_data = prepare_training_data(historical_data)
    # Shape: 50,000 samples × 30 features
    
    # 3. Split data
    train_set, val_set = split_data(training_data, ratio=0.7)
    
    # 4. Train ensemble (3 models in parallel)
    logger.info("Training LSTM...")
    lstm_model = train_lstm(train_set, config)
    
    logger.info("Training RandomForest...")
    rf_model = train_rf(train_set, config)
    
    logger.info("Building Markov chain...")
    markov_model = build_markov(train_set, config)
    
    # 5. Ensemble + weight initialization
    ensemble_new = EnsembleModel(lstm_model, rf_model, markov_model)
    ensemble_new.weight_tracker.reset_weights()
    
    # 6. Evaluate on validation set
    logger.info("Evaluating ensemble...")
    new_accuracy = evaluate_ensemble(ensemble_new, val_set)
    logger.info(f"New model accuracy: {new_accuracy:.4f}")
    
    # 7. Compare with current model
    ensemble_current = load_active_model()
    current_accuracy = evaluate_ensemble(ensemble_current, val_set)
    logger.info(f"Current model accuracy: {current_accuracy:.4f}")
    
    # 8. Drift detection
    logger.info("Checking for concept drift...")
    drift_detected = drift_detector.add_element(new_accuracy)
    if drift_detected:
        logger.warning(f"CONCEPT DRIFT DETECTED! Difference: {abs(new_accuracy - current_accuracy):.4f}")
    
    # 9. Decision: deploy or keep current
    if new_accuracy > current_accuracy + 0.01:  # 1% improvement threshold
        logger.info("Deploying new model...")
        model_registry.save_model(ensemble_new, 'ensemble')
        logger.info("New model saved. API servers will detect and reload.")
    else:
        logger.info("No significant improvement. Keeping current model.")
    
    # 10. Cleanup
    logger.info("Cleanup old temporary files...")
    model_registry.cleanup_temp_files()
    
    logger.info("Training cycle complete!")
```

---

## Monitoring & Observability

### Key Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Training metrics
training_cycles_total = Counter(
    'ml_training_cycles_total',
    'Total training cycles completed',
    ['status']  # 'success', 'failed', 'skipped'
)

training_duration_seconds = Histogram(
    'ml_training_duration_seconds',
    'Time to complete training cycle'
)

model_accuracy = Gauge(
    'ml_model_accuracy',
    'Current ensemble model accuracy on validation set'
)

model_version = Gauge(
    'ml_model_version',
    'Current ensemble model version number'
)

training_dataset_size = Gauge(
    'ml_training_dataset_size',
    'Number of samples in latest training set'
)

concept_drift_detected = Counter(
    'ml_concept_drift_detected_total',
    'Number of concept drift detections'
)
```

### Example Prometheus Alerts

```yaml
groups:
- name: ml_training
  rules:
  - alert: TrainingCycleFailed
    expr: |
      rate(ml_training_cycles_total{status="failed"}[1h]) > 0
    for: 1h
    annotations:
      summary: "ML training cycle failed"
      description: "Training failed {{ $value }} times in last hour"
  
  - alert: ModelAccuracyLow
    expr: ml_model_accuracy < 0.60
    for: 2h
    annotations:
      summary: "Model accuracy below 60%"
      description: "Current accuracy: {{ $value }}"
  
  - alert: ConceptDriftDetected
    expr: |
      increase(ml_concept_drift_detected_total[24h]) > 2
    annotations:
      summary: "Concept drift detected multiple times"
      description: "{{ $value }} drift detections in 24h"
```

---

## Configuration Reference

### Training Config

```env
# Training cycle
ML_TRAINING_ENABLED=true
ML_TRAINING_INTERVAL_HOURS=6                      # Every 6 hours
ML_TRAINING_DATA_RETENTION_DAYS=7                 # Use last 7 days

# LSTM hyperparameters
ML_LSTM_INPUT_SIZE=30
ML_LSTM_HIDDEN_SIZE=64
ML_LSTM_NUM_LAYERS=2
ML_LSTM_DROPOUT=0.2
ML_LSTM_LEARNING_RATE=0.001
ML_LSTM_MAX_EPOCHS=50
ML_LSTM_EARLY_STOPPING_PATIENCE=10
ML_LSTM_EARLY_STOPPING_MIN_DELTA=0.001

# RandomForest hyperparameters
ML_RF_N_ESTIMATORS=100
ML_RF_MAX_DEPTH=15
ML_RF_MIN_SAMPLES_SPLIT=5
ML_RF_MIN_SAMPLES_LEAF=2
ML_RF_MAX_FEATURES=sqrt

# Markov chain
ML_MARKOV_MAX_TRANSITIONS=100000
ML_MARKOV_SMOOTHING=0.1

# Ensemble
ML_ENSEMBLE_LSTM_WEIGHT=0.5
ML_ENSEMBLE_RF_WEIGHT=0.3
ML_ENSEMBLE_MARKOV_WEIGHT=0.2
ML_ENSEMBLE_WEIGHT_WINDOW=1000                    # Accesses to track for weighting

# Drift detection
ML_DRIFT_DETECTION_ENABLED=true
ML_DRIFT_EWMA_ALPHA=0.3
ML_DRIFT_THRESHOLD=0.02                           # 2% accuracy drop

# Model deployment
ML_Model_IMPROVEMENT_THRESHOLD=0.01                # 1% minimum
ML_MODEL_VALIDATION_SIZE_RATIO=0.3                # 30% for validation
```

---

## Common Issues

### Training Takes Too Long

**Symptom**: Training cycle > 4 hours (should be ~30 mins)

**Causes**:
- Too much historical data (> 14 days)
- LSTM training not converging (> 50 epochs)
- RandomForest too large (n_estimators > 200)

**Solution**:
```env
# Reduce data window
ML_TRAINING_DATA_RETENTION_DAYS=7    # was 14

# Reduce ensemble sizes
ML_LSTM_MAX_EPOCHS=30               # was 50
ML_RF_N_ESTIMATORS=50               # was 100

# Increase early stopping aggressiveness
ML_LSTM_EARLY_STOPPING_PATIENCE=5   # was 10
```

### Model Accuracy Low

**Symptom**: ml_model_accuracy < 0.50

**Causes**:
- Not enough training data
- Feature engineering not capturing patterns
- Class imbalance (rare keys underfitting)

**Solution**:
```python
# 1. Increase data retention
ML_TRAINING_DATA_RETENTION_DAYS=14  # was 7

# 2. Add features
# Add domain-specific features (timezone, geographic locality)

# 3. Fix class imbalance
# Use sample weighting (already implemented)
```

### Model Stuck at Same Version

**Symptom**: model_version unchanged for 48+ hours

**Causes**:
- Training not running (check cron job)
- Model improvement threshold too high (> 5%)
- Training errors (check logs)

**Solution**:
```bash
# Debug manually
cd /path/to/pskc
python -m src.ml.trainer --verbose

# Check logs
tail -f logs/api/train*.log

# Verify training is scheduled
crontab -l
# or
kubectl get cronjobs
```

---

## Best Practices

1. **Monitor Training Time**: Alert if > 1 hour
2. **Validate Deployments**: Always test on validation set before serving
3. **Keep Old Models**: Archive for rollback (keep 3-4 versions)
4. **Log Everything**: Hyperparameters, accuracies, drift scores
5. **Gradual Rollout**: Deploy new model to 10% of traffic first
6. **A/B Test**: Compare new vs current model on real traffic
7. **Retrain Regularly**: Even without code changes (data distributions shift)

---

## Related Components

- **DataCollector**: `src/ml/data_collector.py` - Collects access events
- **FeatureEngineer**: `src/ml/feature_engineering.py` - Extracts features
- **ModelRegistry**: `src/ml/model_registry.py` - Version control + verification
- **KeyPredictor**: `src/ml/predictor.py` - Uses trained model at runtime
- **Trainer**: `scripts/train_model.py` - Orchestrates training
