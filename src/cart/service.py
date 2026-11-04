from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.cart.models import Cart, CartItem
from src.cart.schemas import CartItemSchema, CartSchema
from src.movies.models import Movie


async def get_cart_id(db: AsyncSession, user_id: int) -> int | None:
    return await db.scalar(select(Cart.id).where(Cart.user_id == user_id))


async def get_or_create_cart_id(db: AsyncSession, user_id: int) -> int:
    """The user's cart id; the cart is created on first use. Safe for two concurrent first requests."""
    await db.execute(insert(Cart).values(user_id=user_id).on_conflict_do_nothing(index_elements=[Cart.user_id]))
    return (await db.execute(select(Cart.id).where(Cart.user_id == user_id))).scalar_one()


def item_schema(movie: Movie, item: CartItem) -> CartItemSchema:
    return CartItemSchema(
        movie_id=movie.id,
        name=movie.name,
        price=movie.price,
        year=movie.year,
        genres=sorted(genre.name for genre in movie.genres),
        added_at=item.added_at,
    )


async def get_cart(db: AsyncSession, user_id: int) -> CartSchema:
    """The user's cart in the order the movies were added; an empty cart if the user has none yet."""
    stmt = (
        select(Movie, CartItem)
        .join(CartItem, CartItem.movie_id == Movie.id)
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(Cart.user_id == user_id)
        .order_by(CartItem.added_at, CartItem.id)
        .options(selectinload(Movie.genres))
    )
    items = [item_schema(movie, item) for movie, item in await db.execute(stmt)]
    return CartSchema(items=items, total_price=sum((item.price for item in items), Decimal("0.00")))


async def count_carts_with_movie(db: AsyncSession, movie_id: int) -> int:
    stmt = select(func.count()).select_from(CartItem).where(CartItem.movie_id == movie_id)
    return (await db.execute(stmt)).scalar_one()
