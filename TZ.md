General Description: Online Cinema

An online cinema is a digital platform that allows users to select, watch, and purchase access to movies and other video materials via the internet. These services have become popular due to their convenience, a wide selection of content, and the ability to personalize the user experience.
Key Features of Online Cinema
1. Authorization and Authentication

    User Registration:
        Users should be able to register using their email. After registration, an email is sent with a link to activate their account. If the user does not activate their account within 24 hours, the link becomes invalid.
        If the user fails to activate their account within 24 hours, they should have the option to enter their email to receive a new activation link, valid for another 24 hours.
        Use celery-beat to periodically delete expired activation tokens.
        Ensure email uniqueness before registration.

    Login and Logout:
        Provide a logout feature that deletes the user's JWT token, making it unusable for further logins.

    Password Management:
        Users can change their password if they remember the old one by entering the old password and a new password.
        Users who forget their password can enter their email. If the email is registered and active, a reset link is sent, allowing them to set a new password without confirming the old one.
        Enforce password complexity validation.

    JWT Token Management:
        Users receive a pair of JWT tokens (access and refresh) upon login.
        Users can use the refresh token to obtain a new access token with a shorter time-to-live (TTL).

    User Groups:
        Create three user groups:
            User: Access to the basic user interface.
            Moderator: In addition to catalog and user interface access, can manage movies on the site through the admin panel, view sales, etc.
            Admin: Inherits all permissions from the above roles and can manage users, change group memberships, and manually activate accounts.

Entities and Their Attributes

UserGroupEnum (enum) Enumeration of possible user groups (roles):

    USER: A regular user with basic interface access.
    MODERATOR: A user who, in addition to the basic interface, can manage content (e.g., movies), view sales, and perform some administrative tasks.
    ADMIN: A user with extended rights. Can manage other users, change their groups, and manually activate accounts.

GenderEnum (enum) Enumeration for storing a user’s gender:

    MAN
    WOMAN

This field is optional.

UserGroup (user_groups table) Stores user groups. Attributes:

    id: Primary key (int).
    name: Name of the group (USER, MODERATOR, ADMIN), unique field.

Relationships:

    One-to-many: One UserGroup can be related to many User records.

User (users table) Represents registered users. Attributes:

    id: Primary key (int).
    email: User’s email, unique and required, used for login and identification.
    hashed_password: User’s password hash, stored securely (not in plain text).
    is_active: Boolean field indicating whether the account is activated. Initially False, becomes True after activation.
    created_at: Timestamp of when the user was created.
    updated_at: Timestamp of the user’s last data update.
    group_id: Foreign key referencing UserGroup, indicating the group the user belongs to (User, Moderator, Admin).

Relationships:

    One-to-many with UserGroup (via group_id): Each user belongs to exactly one group.
    One-to-one with UserProfile: Each user can have one profile with additional information.
    One-to-many with ActivationToken, PasswordResetToken, RefreshToken.

UserProfile (user_profiles table) Additional user information. Attributes:

    id: Primary key (int).
    user_id: Foreign key referencing users. Unique, ensuring a one-to-one relationship with User.
    first_name: User’s first name (optional).
    last_name: User’s last name (optional).
    avatar: A link or identifier for the user’s avatar (e.g., a key in S3 storage).
    gender: Gender (MAN/WOMAN), optional.
    date_of_birth: Date of birth, optional.
    info: A text field for a short bio or additional user info.

Relationships:

    One-to-one with User.

ActivationToken (activation_tokens table) A token for account activation, sent to the user’s email after registration. Attributes:

    id: Primary key (int).
    user_id: Foreign key referencing users. Unique, ensuring a one-to-one relationship with User.
    token: A unique token.
    expires_at: The token’s expiration time (24 hours after issuance).

Tasks:

    Create a new ActivationToken upon registration.
    If the user does not activate their account within 24 hours, the token becomes invalid.
    Allow resending a new token if the old one expires.
    Use celery-beat to periodically remove expired tokens.

PasswordResetToken (password_reset_tokens table) A token for resetting a forgotten password, sent to the user’s email upon request. Attributes:

    id: Primary key (int).
    user_id: Foreign key referencing users. Unique, ensuring a one-to-one relationship with User.
    token: A unique password reset token.
    expires_at: The token’s expiration time.

Tasks:

    If a user forgets their password, generate and send a reset token via email.
    With this token, the user can set a new password without knowing the old one.
    Check the token’s validity period.

RefreshToken (refresh_tokens table) A refresh token to obtain a new access token without re-entering login credentials. Attributes:

    id: Primary key (int).
    user_id: Foreign key referencing users.
    token: A unique refresh token.
    expires_at: The refresh token’s expiration time.

Tasks:

    On login, the user receives a pair of tokens: access and refresh.
    When the access token expires, the user can use the refresh token to get a new access token.
    On logout, the refresh token is deleted, preventing further use.

Functional Requirements (Summary):

    Registration with an activation email.
    Account activation using the received token.
    Resending the activation token if the previous one expires.
    Use celery-beat to periodically remove expired tokens.
    Login that issues JWT tokens (access and refresh).
    Logout that revokes the refresh token.
    Password reset with a token sent via email.
    Enforce password complexity checks when changing or setting a new password.
    User groups (User, Moderator, Admin) with different sets of permissions.
    Allow administrators to change a user’s group and manually activate accounts.

DB schema

    Accounts DB schema

2. Movies

    User Functionality:
        Browse the movie catalog with pagination.
        View detailed descriptions of movies.
        Like or dislike movies.
        Write comments on movies.
        Filter movies by various criteria (e.g., release year, IMDb rating).
        Sort movies by different attributes (e.g., price, release date, popularity).
        Search for movies by title, description, actor, or director.
        Add movies to favorites and perform all catalog functions (search, filter, sort) on the favorites list.
        Remove movies from favorites.
        View a list of genres with the count of movies in each. Clicking on a genre shows all related movies.
        Rate movies on a 10-point scale.
        Notify users when their comments receive replies or likes.

    Moderator Functionality:
        Perform CRUD operations on movies, genres, and actors.
        Prevent the deletion of a movie if at least one user has purchased it.

Entities and Their Attributes

    Genre (genres table) Represents a movie genre (e.g., Action, Drama, Comedy). Attributes:
        id: Primary key (int), auto-incremented.
        name: The genre’s name (e.g., "Action"). Must be unique and not null.

    Relationships:
        Many-to-many with Movie through the movie_genres association table. A single genre can be associated with multiple movies, and a single movie can belong to multiple genres.

    Star (stars table) Represents an actor or actress starring in a movie. Attributes:
        id: Primary key (int), auto-incremented.
        name: The star’s name. Must be unique and not null.

    Relationships:
        Many-to-many with Movie through the movie_stars association table. A star can appear in multiple movies, and a movie can have multiple stars.

    Director (directors table) Represents a movie director. Attributes:
        id: Primary key (int), auto-incremented.
        name: The director’s name. Must be unique and not null.

    Relationships:
        Many-to-many with Movie through the movie_directors association table. A director can direct multiple movies, and a movie can have multiple directors.

    Certification (certifications table) Represents the rating or certification of a movie (e.g., PG-13, R). Attributes:
        id: Primary key (int), auto-incremented.
        name: The certification name. Must be unique and not null (e.g., "PG-13").

    Relationships:
        One-to-many with Movie: One certification can be applied to many movies, but each movie has exactly one certification.

    Movie (movies table) Represents a movie’s main data. Attributes:
        id: Primary key (int), auto-incremented.
        uuid: A unique UUID for the movie, ensuring global uniqueness.
        name: The movie’s title (string, not null).
        year: The release year (int, not null).
        time: The movie’s duration in minutes (int, not null).
        imdb: The movie’s IMDb rating (float, not null).
        votes: The number of votes on IMDb (int, not null).
        meta_score: Metascore (float, optional).
        gross: Gross revenue (float, optional).
        description: A textual description or synopsis (text, not null).
        price: The price of the movie (DECIMAL(10,2)).
        certification_id: Foreign key to certifications.id (int, not null). This field ensures that the movie’s rating is always defined.

    Constraints:
        A unique constraint on (name, year, time), ensuring that the combination of title, release year, and duration uniquely identifies a movie.

    Relationships:
        Many-to-one with Certification (via certification_id): Each movie has one certification.
        Many-to-many with Genre (via movie_genres): A movie can belong to multiple genres.
        Many-to-many with Director (via movie_directors): A movie can have multiple directors.
        Many-to-many with Star (via movie_stars): A movie can feature multiple stars.

Association Tables

    movie_genres: Connects Movie and Genre (many-to-many). Columns:
        movie_id: Foreign key to movies.id, part of composite primary key.
        genre_id: Foreign key to genres.id, part of composite primary key.

    movie_directors: Connects Movie and Director (many-to-many). Columns:
        movie_id: Foreign key to movies.id, part of composite primary key.
        director_id: Foreign key to directors.id, part of composite primary key.

    movie_stars: Connects Movie and Star (many-to-many). Columns:
        movie_id: Foreign key to movies.id, part of composite primary key.
        star_id: Foreign key to stars.id, part of composite primary key.

DB schema

    Movies DB schema

3. Shopping Cart

    User Functionality:
        Users can add movies to the cart if they have not been purchased yet.
        If the movie has already been purchased, a notification is displayed, indicating that repeat purchases are not allowed.
        Users can remove movies from the cart if they decide not to proceed with the purchase.
        Users can view a list of movies in their cart.
        For each movie in the cart, the title, price, genre, and release year are displayed.
        Users can pay for all movies in the cart at once.
        After successful payment, movies are moved to the "Purchased" list.
        Users can manually clear the cart entirely.
        Validation:
            Ensure all movies are available for purchase before creating an order.
            Exclude movies already purchased, notifying the user.
            Prompt unregistered users to sign up before completing a purchase.
            Prevent adding the same movie to the cart more than once.

    Moderator Functionality:
        Admins can view the contents of users' carts for analysis or troubleshooting.
        Notify moderators when attempting to delete a movie that exists in users' carts.

Below is a detailed description of the entities and their attributes for the Shopping Cart functionality. These entities assume that User and Movie are defined elsewhere and are imported into this module.

Entities and Their Attributes

    Cart (carts table) Represents a user's shopping cart. Each user can have exactly one cart. Attributes:
        id: Primary key (int), auto-incremented.
        user_id: Foreign key referencing users.id, not null and unique, ensuring a one-to-one relationship with the user.

    Relationships:
        One-to-one with User: Each user has exactly one Cart, and each Cart belongs to one User.
        One-to-many with CartItem: A cart can contain multiple cart items.

    Key Points:
        The unique constraint on user_id guarantees that each user can have only one cart.
        Acts as a container for CartItem records.

    CartItem (cart_items table) Represents a single item (movie) placed in a user's cart. Attributes:
        id: Primary key (int), auto-incremented.
        cart_id: Foreign key referencing carts.id, not null, indicating which cart the item belongs to.
        movie_id: Foreign key referencing movies.id, not null, indicating which movie is added to the cart.
        added_at: Timestamp of when the movie was added to the cart, defaults to the current time.

    Relationships:
        Many-to-one with Cart: Each CartItem belongs to exactly one Cart.
        Optionally, a many-to-one relationship with Movie can be defined if needed. Each CartItem references exactly one Movie.

    Constraints:
        A unique constraint on (cart_id, movie_id) ensures that the same movie cannot be added to a single cart more than once.

Summary of Relationships

    User - Cart (1:1): Each user can have one unique cart.
    Cart - CartItem (1:n): One cart can have many cart items.
    CartItem - Movie (n:1) (optional explicit relationship): Each cart item represents a single movie.

Functional Implications

    A User can manage their cart (add, remove, or clear items).
    A Cart ensures centralized management of all items a user wants to purchase.
    The CartItem model enforces uniqueness of movies in a user's cart and tracks when items were added, which can be useful for UI features or analytics.

DB schema

    Cart DB schema

4. Order

    User Functionality:
        Users can place orders for movies in their cart.
        If movies are unavailable (e.g., deleted, region-locked), they are excluded from the order with a notification to the user.
        Users can view a list of all their orders.
        For each order, the following details are displayed:
            Date and time.
            List of movies included.
            Total amount.
            Order status (paid, canceled, pending).
        After confirming an order, users are redirected to a payment gateway.
        Users can cancel orders before payment is completed.
        Once paid, orders can only be canceled via a refund request.
        After successful payment, users receive an email confirmation.
        Validation:
            Ensure the cart is not empty before placing an order.
            Exclude movies already purchased by the user.
            Ensure all movies in the order are available for purchase.
            Check that no other orders with the same movies are already pending.
            Revalidate the total amount before payment in case of price changes.

    Moderator Functionality:
        Admins can view all user orders with filters for:
            Users.
            Dates.
            Statuses (paid, canceled, etc.).

Below is a detailed description of the Order and OrderItem entities and their attributes, including their relationships and significance within the ordering process.

Entities and Their Attributes

    Order (orders table) Represents a user's order containing one or more movies.

    Attributes:
        id: Primary key (int, auto-incremented).
        user_id: Foreign key referencing users.id (int, not null), indicating which user owns the order.
        created_at: The date and time the order was created (timestamp with time zone, defaults to the current time).
        status: The current status of the order. Stored as an enum with possible values:
            pending: The order has been placed but not paid yet.
            paid: The order has been successfully paid.
            canceled: The order has been canceled by the user or through another process. Must not be null and defaults to pending.
        total_amount: The total cost of all items in the order at the time of creation (DECIMAL(10, 2), optional and can be recalculated before payment).

    Relationships:
        One-to-many with OrderItem: An order can contain multiple order items, each representing a movie included in this order.
        Many-to-one with User: Each order is associated with a single user, who can have many orders over time.

    Key Points:
        Order provides a snapshot of which movies the user intends to purchase at a given moment.
        The status field allows tracking the lifecycle of the order: pending, then paid, or canceled.
        The total_amount can be checked or updated before finalizing payment, ensuring accurate billing.

    OrderItem (order_items table) Represents a single line item within an order, linking a specific movie to the order.

    Attributes:
        id: Primary key (int, auto-incremented).
        order_id: Foreign key referencing orders.id (int, not null), indicating which order this item belongs to.
        movie_id: Foreign key referencing movies.id (int, not null), indicating which movie is included in the order.
        price_at_order: The price of the movie at the time the order was created (DECIMAL(10, 2), not null). Storing the price at order time ensures price changes do not retroactively affect historical orders.

    Relationships:
        Many-to-one with Order: Each order item belongs to exactly one order.
        Many-to-one with Movie: Each order item references exactly one movie.

    Key Points:
        OrderItem provides a breakdown of the order contents.
        Storing price_at_order ensures historical accuracy of the order data, even if movie prices change later.

Summary of Relationships

    User (1) -- (n) Order: A single user can have multiple orders.
    Order (1) -- (n) OrderItem: A single order can contain multiple items.
    Movie (1) -- (n) OrderItem: A single movie can appear in many orders from various users.

Functional Implications

    Users can track their order history, including the movies purchased, the final amount paid, and the current status of each order.
    The presence of price_at_order in OrderItem ensures that financial records remain consistent over time, essential for audits, refunds, and reporting.
    The status field in Order allows for workflow management, including pending payment, cancellation, and handling refunds.

DB schema

    Order DB schema

5. Payments

    User Functionality:
        Users can make payments using Stripe.
        After payment, users receive a confirmation on the website and via email.
        Users can view the history of all their payments, including:
            Date and time.
            Amount.
            Status (successful, canceled, refunded).
        Validation:
            Verify the total amount of the order.
            Check the availability of the selected payment method.
            Ensure the user is authenticated.
            Validate transactions through webhooks provided by the payment system.
            Update the order status upon successful payment.
            If a transaction is declined, display recommendations to the user (e.g., "Try a different payment method").

    Moderator Functionality:
        Admins can view a list of all payments with filters for:
            Users.
            Dates.
            Statuses (successful, refunded, canceled).

Entities and Their Attributes

    Payment (payments table) Represents a payment transaction made by a user for an order.

    Attributes:
        id: Primary key (int, auto-incremented).
        user_id: Foreign key referencing users.id (int, not null), indicating which user made this payment.
        order_id: Foreign key referencing orders.id (int, not null), indicating which order this payment is associated with.
        created_at: Timestamp recording when the payment was created (timestamp with time zone, defaults to the current time).
        status: Current status of the payment, stored as an enum. Possible values include:
            successful: The payment has been completed successfully.
            canceled: The payment was canceled before completion.
            refunded: The amount was refunded after a successful payment. Defaults to successful, but can be changed as the transaction progresses through its lifecycle.
        amount: The total amount of the payment (DECIMAL(10,2), not null), ensuring accurate financial records even if the order's pricing changes.
        external_payment_id: An optional string field to store the external transaction ID from the payment provider (e.g., Stripe's charge_id), enabling easy cross-referencing and validation.

    Relationships:
        Many-to-one with User: Each payment is linked to a specific user.
        Many-to-one with Order: Each payment is associated with a single order, though an order might have multiple payments if partial or incremental payments are allowed in the future.
        One-to-many with PaymentItem: A payment can consist of multiple items, each corresponding to a line item in the order.

    Key Points:
        Payment records serve as the financial transactions linked to orders.
        Storing external_payment_id and status allows integration with payment gateways and easy tracking of payment lifecycle.

    PaymentItem (payment_items table) Represents an individual item paid for in a single payment, mirroring an order line item at the time of payment.

    Attributes:
        id: Primary key (int, auto-incremented).
        payment_id: Foreign key referencing payments.id (int, not null), indicating which payment this item belongs to.
        order_item_id: Foreign key referencing order_items.id (int, not null), linking back to the original order line item.
        price_at_payment: The price of the specific order item at the time of payment (DECIMAL(10,2), not null). This ensures the payment record remains historically accurate, even if prices change later.

    Relationships:
        Many-to-one with Payment: Each payment item belongs to exactly one payment.
        Many-to-one with OrderItem: Each payment item references an OrderItem to provide context for what was actually paid for.

    Key Points:
        PaymentItem captures a snapshot of the pricing and items at the exact moment of payment.
        This granular data allows for detailed financial reporting, refunds of individual items, and easy reconciliation of payments against orders.

Summary of Relationships

    User (1) -- (n) Payment: A user can have multiple payments over time.
    Order (1) -- (n) Payment: An order can be associated with one or more payments (if partial payments are introduced).
    Payment (1) -- (n) PaymentItem: A payment can cover multiple order items.
    OrderItem (1) -- (n) PaymentItem: Multiple payment items can reference different order items of potentially the same order, allowing flexible payment structures.

Functional Implications

    Users have a clear history of all their payments, including details of when, how much, and which items were paid for.
    The status field and external_payment_id facilitate robust integration with external payment gateways (like Stripe), enabling features like refunds, cancellations, and transaction validations through webhooks.
    Detailed payment itemization (PaymentItem) supports precise financial audits, reporting, and troubleshooting in case of disputes or inquiries.

DB schema

    Payment DB schema

6. Docker and Docker Compose

    Project Containerization:
        Use Docker to containerize the project and manage related services efficiently.
    Service Management:
        Deploy multiple services like FastAPI, Redis, Celery, and MinIO using Docker Compose.
    Custom Docker Images:
        Create and maintain Docker images for the FastAPI application and related services.
    Single Command Setup:
        Use a single command to launch all services via Docker Compose for streamlined development and deployment.

7. Poetry for Dependency Management

    Dependency Simplification:
        Use Poetry for easy dependency management and virtual environment handling.
    Project Dependencies:
        Install required project dependencies via Poetry commands.
    Configuration File:
        Use pyproject.toml to specify all dependencies, versions, and additional configurations.
    Environment Management:
        Manage virtual environments seamlessly within the development workflow.

8. CI/CD with GitHub Actions

    Automated Processes:
        Configure GitHub Actions to automate code quality checks, testing, and deployment pipelines.
    Code Quality Checks:
        Run linters such as flake8 or black to ensure code consistency.
        Perform type checking with mypy to validate type annotations.
    Testing Automation:
        Execute all tests using pytest to validate functionality.
        Generate and review code coverage reports for quality assurance.
    Continuous Deployment:
        Automatically deploy the application after passing all checks and merging pull requests to AWS EC2.

9. Swagger Documentation Requirements

    OpenAPI Specification:
        Use OpenAPI Specification (version 3.0 or above) for documentation.
    Complete API Documentation:
        Ensure all API endpoints are fully documented for developers and stakeholders.
    Access Control:
        Restrict access to API documentation, allowing visibility only for authorized users.

10. Writing Tests

    API Endpoint Testing:
        Verify that endpoints return correct responses.
        Test error handling and ensure proper feedback for invalid inputs.
    Validation Testing:
        Ensure business rules and validation logic work correctly (e.g., authentication, filtering, and sorting).
    Unit Tests:
        Coverage:
            Data validation logic.
            Utility functions.
            Individual business rules.
    Integration Tests:
        Coverage:
            Interaction between endpoints and the database.
            Authentication workflows, including JWT processing.
    Functional Tests:
        Cover end-to-end user scenarios such as registration, login, movie filtering, and order placement.
