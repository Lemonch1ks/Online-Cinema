from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.dependencies import get_current_active_user, require_role
from src.auth.models import User, UserGroupEnum
from src.cart.models import CartItem
from src.cart.schemas import CartItemInSchema, CartItemSchema, CartSchema
from src.cart.service import get_cart, get_cart_id, get_or_create_cart_id, item_schema
from src.core.database import get_db
from src.movies.models import Movie
from src.orders.models import OrderStatusEnum
from src.orders.services import movie_ids_in_orders

router = APIRouter()

MOVIE_NOT_FOUND_RESPONSE = {
    "description": "Movie with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No movies with id:1 found."}}},
}


@router.get(
    "/cart",
    response_model=CartSchema,
    summary="Get Cart",
    description="The current user's cart: movies in the order they were added and the total price.",
)
async def read_cart(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    return await get_cart(db, user.id)


@router.post(
    "/cart/items",
    status_code=status.HTTP_201_CREATED,
    response_model=CartItemSchema,
    summary="Add Movie to Cart",
    responses={
        404: MOVIE_NOT_FOUND_RESPONSE,
        409: {"description": "The movie is already in the cart or already purchased."},
    },
)
async def add_to_cart(
    data: CartItemInSchema,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CartItemSchema:
    stmt = select(Movie).where(Movie.id == data.movie_id).options(selectinload(Movie.genres))
    movie = await db.scalar(stmt)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No movies with id:{data.movie_id} found.")
    if movie.id in await movie_ids_in_orders(db, user.id, OrderStatusEnum.paid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Movie with id:{movie.id} is already purchased."
        )

    cart_id = await get_or_create_cart_id(db, user.id)
    item = await db.scalar(
        insert(CartItem).values(cart_id=cart_id, movie_id=movie.id).on_conflict_do_nothing().returning(CartItem)
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Movie with id:{movie.id} is already in the cart."
        )
    await db.commit()
    return item_schema(movie, item)


@router.delete(
    "/cart/items/{movie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Movie from Cart",
    responses={404: {"description": "The movie is not in the cart."}},
)
async def remove_from_cart(
    movie_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    cart_id = await get_cart_id(db, user.id)
    stmt = delete(CartItem).where(CartItem.cart_id == cart_id, CartItem.movie_id == movie_id).returning(CartItem.id)
    if (await db.execute(stmt)).first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Movie with id:{movie_id} is not in the cart."
        )
    await db.commit()


@router.delete(
    "/cart",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear Cart",
    description="Removes all movies from the current user's cart.",
)
async def clear_cart(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    cart_id = await get_cart_id(db, user.id)
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
    await db.commit()


@router.get(
    "/admins/carts/{user_id}",
    dependencies=[Depends(require_role(UserGroupEnum.ADMIN))],
    response_model=CartSchema,
    summary="Get User's Cart",
    description="Admins only: the cart of any user, for analysis or troubleshooting.",
    responses={404: {"description": "User not found."}},
)
async def read_user_cart(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    if await db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await get_cart(db, user_id)
