"""Simulation-only stabilization gate."""
def stabilization_simulated_success(*,children_verified:bool,stable_samples:int=2,required_samples:int=2)->bool:return children_verified and stable_samples>=required_samples
