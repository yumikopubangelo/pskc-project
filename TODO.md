# PSKC API Frontend Calls Fix - TODO List

## Plan Breakdown
1. [x] ✅ Add CORSMiddleware to src/api/routes.py to enable frontend POST requests
2. [ ] Test ML endpoints: curl POST http://localhost:8000/ml/training/generate?num_events=100
3. [ ] Reload backend (docker compose restart api)
4. [ ] Test in browser MLTraining page: click "Generate Training Data" → check Network tab
5. [ ] If train fails (insufficient samples), test POST /ml/data/import
6. [ ] Verify uvicorn logs show /ml/* calls
7. [ ] [DONE] attempt_completion

**Status:** CORS added. Backend restart needed (docker compose restart api). Test endpoints next.


