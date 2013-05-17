`xact` is a recipe for handling transactions sensibly in Django applications on PostgreSQL.

**Note**: As of Django 1.6, the functionality of `xact` will be merged into the Django core as the [`atomic` decorator](https://docs.djangoproject.com/en/dev/topics/db/transactions/#django.db.transaction.atomic).
Code that uses `xact` should be able to be migrated to `atomic` with just a search-and-replace.

The goals are:

* Database operations that do not modify the database aren't wrapped in a transactions at all.
* Database operations that modify the database are wrapped in a transactions.
* We have a lot of fine-grained control over sections that modify the databse vs those that don't.

The bits of the recipe are:

* Use the [autocommit option](https://docs.djangoproject.com/en/dev/ref/databases/#autocommit-mode) in your database configuration.
* *Do not* use the [transaction middleware](https://docs.djangoproject.com/en/dev/topics/db/transactions/#tying-transactions-to-http-requests).
* Wrap the sections of code which modify the database in the `xact()` decorator / context manager below, using it like you would the [`commit_on_success()`](https://docs.djangoproject.com/en/dev/topics/db/transactions/#controlling-transaction-management-in-views) decorator.
* Profit!

The quick reasons behind each step:

* Turning on autocommit prevents [psycopg2](http://initd.org/psycopg/) from automatically starting a new transaction on the first database operation on each connection; this means that the transaction only starts when we want it to.
* Similarly, the transaction middleware will set the connection state to "managed," which will defeat the autocommit option above, so we leave it out.
* The `xact()` decorator will set up the connection so that a transaction *is* started in the relevant block, which is what we want for database-modifying operations.

This recipe a few other nice features:

* `xact()` operates like `commit_on_success()`, in that it will issue a rollback if an exception escapes from the block or function it is wrapping.
* `xact()` ignores the dirty flag on the Django connection. Since we're deliberately wrapping stuff that modifies the database with it, the chance of it being dirty is near 100%, and a commit on a transaction that did not modify the database is no more expensive in PostgreSQL than a rollback. It also means you can do [raw SQL](https://docs.djangoproject.com/en/dev/topics/db/sql/) inside an `xact()` block without the [foot-gun](http://archives.postgresql.org/pgsql-hackers/2008-06/msg01101.php) of forgetting to call `set_dirty`.
* Like the built-in Django transaction decorators, it can be used either as a decorator or as a context manager with the `with` statement.
* `xact()` can be nested, giving us nested transactions! If it sees that there is already a transaction open when it starts a new block, it will use a [savepoint](http://www.postgresql.org/docs/9.1/static/sql-savepoint.html) to set up a nested transaction block.  (PostgreSQL does not have nested transactions as such, but you can use savepoints to get 99.9% of the way there.)
* By not wrapping operations that do not modify the database, we get better behavior when using [pgPool II](http://www.pgpool.net/) (more on that in a future post).
* `xact()` works around an [outstanding bug](https://code.djangoproject.com/ticket/16047) in Django's transaction handling on psycopg2.

`xact()` also supports the `using` parameter for [multiple databases](https://docs.djangoproject.com/en/dev/topics/db/multi-db/).

Of course, a few caveats:

* `xact()` requires the `postgresql_psycopg2` backend, and PostgreSQL 8.2 or higher. It's possible it can be hacked to work on other backends that support savepoints.
* `xact()` works just the way you want if it is nested *inside* a `commit_on_success()` block (it will properly create a savepoint insted of a new transaction). However, a `commit_on_success()` block nested inside of `xact()` will commit or rollback the entire transaction, somewhat defeating the outer `xact()`. To the extent possible, use only `xact()` in code you write.
* Be sure you catch exceptions *outside of* the `xact()` block; otherwise, the automatic rollback will be defeated. Allow the exception to escape the `xact()` block, and then catch it. (Of course, if the intention is to always commit and to defeat the rollback, by all means catch the exception inside the block.)

To use, just drop the source (one class definition, one function) into a file somewhere in your Django project (such as the omni-present `utils` application every Django project seems to have), and include it. 

Examples:

    from utils.transaction import xact

    @xact
    def my_view_function1(request):
       # Everything here will be in a transaction.
       # It'll roll back if an exception escapes, commits otherwise.

    def my_view_function2(request):
       # This stuff won't be in a transaction, so don't modify the database here.
       with xact():
          # This stuff will be, and will commit on normal completion, roll back on a exception

    def my_view_function3(request):
       with xact():
          # Modify the database here (let's call it "part 1").
          try:
             with xact():
                # Let's call this "part 2."
                # This stuff will be in its own savepoint, and can commit or
                # roll back without losing the whole transaction.
          except:
             # Part 2 will be rolled back, but part 1 will still be available to
             # be committed or rolled back.  Of course, if an exception
             # inside the "part 2" block is not caught, both part 2 and
             # part 1 will be rolled back.

