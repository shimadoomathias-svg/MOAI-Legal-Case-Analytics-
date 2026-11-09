from fastapi import APIRouter

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])

@router.get("/status")
def prediction_status():
    return {
        "status": "foundation_only",
        "message": "The prediction engine will be implemented after comparable-case and sentencing data are available.",
        "method": "Jurisdiction-specific statistical analysis and comparable-case matching",
        "warning": "Any future estimate will be uncertain, data-dependent, and not legal advice."
    }
