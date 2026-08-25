"""Canary admission facade; implementation lives in the compositional pipeline."""
from .pipeline import AdmissionResult,MultiServiceCanaryAdmission
__all__=["AdmissionResult","MultiServiceCanaryAdmission"]
