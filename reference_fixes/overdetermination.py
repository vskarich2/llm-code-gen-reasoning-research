from store import read, get_version
from writer_a import write_fresh


def update_product(product_id, compute_fn):
    """Update product data. Uses fresh writer only."""
    write_fresh(product_id, compute_fn)
    return read(product_id)


def serve_request(product_id):
    """Serve product data with version."""
    return {"value": read(product_id), "version": get_version(product_id)}
