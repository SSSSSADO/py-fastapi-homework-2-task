import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette import status

from database import get_db, MovieModel
from database.models import (
    CountryModel, GenreModel, ActorModel, LanguageModel
)
from schemas.movies import (
    MovieBaseSchema, MovieListResponseSchema, MovieResponseSchema, MovieUpdateSchema, MovieCreateSchema
)


router = APIRouter()


async def get_or_create(session, model, field_name: str, value: str):
    stmt = select(model).where(getattr(model, field_name) == value)
    result = await session.execute(stmt)
    instance = result.scalar_one_or_none()

    if instance:
        return instance

    instance = model(**{field_name: value})
    session.add(instance)
    await session.flush()
    return instance


@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_movies(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * per_page
    total_items_query = await db.execute(select(func.count(MovieModel.id)))
    total_items = total_items_query.scalar()
    total_pages = math.ceil(total_items / per_page)
    result = await db.execute(
        select(MovieModel)
        .order_by(MovieModel.id.desc())
        .offset(offset)
        .limit(per_page)
    )
    movies = result.scalars().all()

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")
    prev_page = None
    if page > 1:
        prev_page = f"/theater/movies/?page={page - 1}&per_page={per_page}"
    next_page = None
    if page < total_pages:
        next_page = f"/theater/movies/?page={page + 1}&per_page={per_page}"

    return {
        "movies": movies,
        "prev_page": prev_page,
        "next_page": next_page,
        "total_pages": total_pages,
        "total_items": total_items
    }


@router.get("/movies/{movie_id}/", response_model=MovieResponseSchema)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(MovieModel).where(MovieModel.id == movie_id).options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages)
        )
    )
    result = await db.execute(query)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    return movie


@router.post("/movies/", response_model=MovieCreateSchema)
async def create_movie(
        payload: MovieCreateSchema, db: AsyncSession = Depends(get_db)
):
    if payload.date > date.today() + timedelta(days=365):
        raise HTTPException(status_code=400, detail="Invalid input data.")

    db_movie = select(MovieModel).where(
        MovieModel.name == payload.name,
        MovieModel.date == payload.date
    )
    result = await db.execute(db_movie)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409, detail=(
                f"A movie with the name '{payload.name}' "
                f"and release date '{payload.date}' already exists."
            )
        )

    country = await get_or_create(db, CountryModel, "code", payload.country)
    movie = MovieModel(
        name=payload.name,
        date=payload.date,
        score=payload.score,
        overview=payload.overview,
        status=payload.status,
        budget=payload.budget,
        revenue=payload.revenue,
        country_id=country.id
    )
    db.add(movie)
    await db.flush()

    genres = []
    for gen in payload.genres:
        genre = await get_or_create(db, GenreModel, "name", gen)
        genres.append(genre)
    movie.genres = genres

    actors = []
    for act in payload.actors:
        actor = await get_or_create(db, ActorModel, "name", act)
        actors.append(actor)
    movie.actors = actors

    languages = []
    for lan in payload.languages:
        language = await get_or_create(db, LanguageModel, "name", lan)
        languages.append(language)
    movie.languages = languages

    await db.commit()
    await db.refresh(movie)
    return movie


@router.patch("/movies/{movie_id}/")
async def update_movie(
        movie_id: int,
        payload: MovieUpdateSchema,
        db: AsyncSession = Depends(get_db)
):
    query = select(MovieModel).where(MovieModel.id == movie_id)
    result = await db.execute(query)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie with the given ID was not found."
        )

    update_data = payload.model_dump(exclude_unset=True)

    if "date" in update_data:
        if update_data["date"] > date.today() + timedelta(days=365):
            raise HTTPException(status_code=400, detail="Invalid input data.")

    try:
        for field, value in update_data.items():
            setattr(movie, field, value)
        await db.commit()
        return {"detail": "Movie updated successfully."}
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")


@router.delete("/movies/{movie_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    query = select(MovieModel).where(MovieModel.id == movie_id)
    result = await db.execute(query)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    await db.delete(movie)
    await db.commit()
