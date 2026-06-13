from app import app, db, User, Portfolio, Transaction
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_fix():
    with app.app_context():
        try:
            # 1. Create a test user
            test_user = User(
                username='schema_test_user',
                email='schema_test@example.com',
                password='hashed_password_here'
            )
            db.session.add(test_user)
            db.session.commit()
            logger.info("Test user created")

            # 2. Try to insert a long stock symbol (30+ characters)
            long_symbol = "VERY_LONG_STOCK_SYMBOL_THAT_EXCEEDS_TEN_CHARACTERS"
            logger.info(f"Attempting to insert symbol with length: {len(long_symbol)}")
            
            # Test Portfolio insertion
            test_portfolio = Portfolio(
                stock_symbol=long_symbol,
                quantity=10,
                buy_price=150.0,
                user_id=test_user.id
            )
            db.session.add(test_portfolio)
            
            # Test Transaction insertion
            test_txn = Transaction(
                stock_symbol=long_symbol,
                type='Buy',
                quantity=10,
                price=150.0,
                user_id=test_user.id
            )
            db.session.add(test_txn)
            
            db.session.commit()
            logger.info("Successfully inserted long stock symbol into multiple tables!")
            print("VERIFICATION SUCCESS: Schema updated and long symbols are supported.")

        except Exception as e:
            logger.error(f"VERIFICATION FAILED: {e}")
            print(f"VERIFICATION FAILED: {e}")
            db.session.rollback()
        finally:
            # Clean up
            try:
                # Need to find the user again because the previous object might be detached
                u = User.query.filter_by(username='schema_test_user').first()
                if u:
                    # Cascade should handle portfolio and transactions if set up, 
                    # but we'll be safe
                    Portfolio.query.filter_by(user_id=u.id).delete()
                    Transaction.query.filter_by(user_id=u.id).delete()
                    db.session.delete(u)
                    db.session.commit()
                    logger.info("Cleaned up test data")
            except Exception as cleanup_err:
                logger.warning(f"Cleanup failed: {cleanup_err}")

if __name__ == "__main__":
    verify_fix()
