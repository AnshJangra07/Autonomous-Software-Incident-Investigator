import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.log_collector import read_error_events
from app.services.incident_analyzer import analyze_incidents
from app.services.investigation_pipeline import investigate_incident

router = APIRouter()

logger = logging.getLogger(__name__)

class InvestigationRequest(BaseModel):
    failure_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    message: str = Field(
        ...,
        min_length=1,
        max_length=1000,
    )

    endpoint: str = Field(
        ...,
        min_length=1,
        max_length=200,
    )


@router.get("/")
def home():

    logger.info(
        "Home endpoint accessed",
        extra={"endpoint": "/"}
    )

    return {
        "message": "E-commerce application is running",
        "application": "ASII Demo Store"
    }


@router.get("/health")
def health_check():

    logger.info(
        "Health check requested",
        extra={"endpoint": "/health"}
    )

    return {
        "status": "healthy",
        "service": "ecommerce-api"
    }


@router.get("/simulate-failure")
def simulate_failure(
    failure_type: str = Query(
        ...,
        pattern="^(database|payment)$"
    )
):

    if failure_type == "database":

        logger.error(
            "Unable to establish database connection",
            extra={
                "endpoint": "/simulate-failure",
                "failure_type": "database",
                "status_code": 503
            }
        )

        raise HTTPException(
            status_code=503,
            detail="Simulated database connection failure"
        )

    if failure_type == "payment":

        logger.error(
            "Payment gateway timeout",
            extra={
                "endpoint": "/simulate-failure",
                "failure_type": "payment",
                "status_code": 502
            }
        )

        raise HTTPException(
            status_code=502,
            detail="Simulated payment gateway timeout"
        )
    
@router.get("/incidents/recent")
def get_recent_incidents(limit: int = Query(20, ge=1, le=100)):

    incidents = read_error_events(limit=limit)

    logger.info(
        "Recent incidents retrieved",
        extra={"endpoint": "/incidents/recent"}
    )

    return {
        "total_incidents": len(incidents),
        "incidents": incidents
    }




@router.get("/incidents/summary")
def get_incident_summary():

    incidents = read_error_events(limit=100)

    summaries = analyze_incidents(incidents)

    logger.info(
        "Incident summary generated",
        extra={"endpoint": "/incidents/summary"}
    )

    return {
        "total_error_events": len(incidents),
        "total_incident_types": len(summaries),
        "incident_summaries": summaries
    }


@router.post("/investigations/run")
def run_investigation(request: InvestigationRequest):

    logger.info(
        "Incident investigation started",
        extra={"endpoint": "/investigations/run"}
    )

    incident = request.model_dump()

    report = investigate_incident(incident)

    logger.info(
        "Incident investigation completed",
        extra={"endpoint": "/investigations/run"}
    )

    return report