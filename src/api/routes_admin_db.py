import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.database.connection import get_db

router = APIRouter(prefix="/api/admin/db", tags=["Database Explorer"])
logger = logging.getLogger(__name__)

@router.get("/tables")
def get_database_tables(db: Session = Depends(get_db)):
    """
    Get a list of all tables in the database with their estimated row counts.
    """
    try:
        engine = db.get_bind()
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        tables_info = []
        for table in table_names:
            # Get estimated row count securely using parameterized literal tables
            # (In SQLite we can just do count(*))
            try:
                # We use text() here, but we only inject names from inspector to be safe
                if not table.isidentifier():
                    continue # Skip strange table names
                count_query = text(f"SELECT COUNT(*) FROM {table}")
                count = db.execute(count_query).scalar()
            except Exception as e:
                logger.warning(f"Could not get count for table {table}: {e}")
                count = -1
                
            tables_info.append({
                "name": table,
                "row_count": count
            })
            
        return {
            "success": True,
            "tables": tables_info
        }
    except Exception as e:
        logger.error(f"Error fetching database tables: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch tables overview")

@router.get("/tables/{table_name}")
def get_table_data(
    table_name: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get paginated rows from a specific table.
    """
    try:
        engine = db.get_bind()
        inspector = inspect(engine)
        
        if table_name not in inspector.get_table_names():
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
            
        # Get column names
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        
        # We must explicitly ensure table_name is an identifier to prevent SQL Injection
        if not table_name.isidentifier():
            raise HTTPException(status_code=400, detail="Invalid table name format")
            
        # Query the data
        query = text(f"SELECT * FROM {table_name} LIMIT :limit OFFSET :offset")
        result = db.execute(query, {"limit": limit, "offset": offset})
        
        rows = []
        for row in result:
            # Convert row to dict. Handle non-serializable objects as strings.
            row_dict = {}
            for index, value in enumerate(row):
                # Standardize datetime serialization manually if needed, 
                # but FastAPI usually handles basic types like datetime
                row_dict[columns[index]] = value
            rows.append(row_dict)
            
        # Get total count
        count_query = text(f"SELECT COUNT(*) FROM {table_name}")
        total_count = db.execute(count_query).scalar()
        
        return {
            "success": True,
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_count,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching data from table {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch data from {table_name}")
