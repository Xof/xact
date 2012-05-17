""" This code provides a decorator / context manager for transaction management in
    Django on PostgreSQL.  It is intended as a replacement for the existing Django
    commit_on_success() function, and provides some nice features:
    
    * Nested transactions: The top-level transaction will be a BEGIN/COMMIT/ROLLBACK
      block; inner "transactions" are implemented as savepoints.
    * Commits even if is_dirty is False, eliminating the mistake of forgetting to set
      the dirty flag when doing database-modifying raw SQL.
    * Better interaction with pgPool II, if you're using it.
    * A workaround for a subtle but nasty bug in Django's transaction management.
    
    As currently implemented, it is NOT thread-safe as a decorator (it IS thread-safe
    as a context manager).  Fix coming.

    For full details, check the README.md file.
"""

from functools import wraps

from django.db import transaction, DEFAULT_DB_ALIAS, connections

import psycopg2.extensions

class _Transaction(object):
    def __init__(self, using):
        self.using = using
        self.sid = None
    
    def __enter__(self):
        if connections[self.using].features.uses_savepoints:
            # We're already in a transaction; create a savepoint.
            self.sid = transaction.savepoint(self.using)
        else:
            transaction.enter_transaction_management(using=self.using)
            transaction.managed(True, using=self.using)
   
    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            # commit operation
            if self.sid is None:
                # Outer transaction
                try:
                    transaction.commit(self.using)
                except:
                    transaction.rollback(self.using)
                    raise
                finally:
                    self._leave_transaction_management()
            else:
                # Inner savepoint
                try:
                    transaction.savepoint_commit(self.sid, self.using)
                except:
                    transaction.savepoint_rollback(self.sid, self.using)
                    raise
        else:
            # rollback operation
            if self.sid is None:
                # Outer transaction
                transaction.rollback(self.using)
                self._leave_transaction_management()
            else:
                # Inner savepoint
                transaction.savepoint_rollback(self.sid, self.using)
        
        return False

    def _leave_transaction_management(self):
        transaction.leave_transaction_management(using=self.using)
        if not connections[self.using].is_managed() and connections[self.using].features.uses_autocommit:
            connections[self.using]._set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            # Patch for bug in Django's psycopg2 backend; see:
            # https://code.djangoproject.com/ticket/16047
    
    # This is a great recipe for allowing a single object to handle both @ decorators
    # and with contexts.
    
    def __call__(self, func):
        @wraps(func)
        def inner(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return inner


def xact(using=None):
    if using is None:
        using = DEFAULT_DB_ALIAS
    if callable(using):
        return _Transaction(DEFAULT_DB_ALIAS)(using)
    return _Transaction(using)


# -----------------------------------------------------------------------------
# This software is licensed under the PostgreSQL License:
#
#   http://www.postgresql.org/about/licence/
# 
# Copyright (c) 2012 Christophe Pettus
# 
# Permission to use, copy, modify, and distribute this software and its
# documentation for any purpose, without fee, and without a written agreement is
# hereby granted, provided that the above copyright notice and this paragraph
# and the following two paragraphs appear in all copies.
# 
# IN NO EVENT SHALL CHRISTOPHE PETTUS BE LIABLE TO ANY PARTY FOR DIRECT,
# INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST
# PROFITS, ARISING OUT OF THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN
# IF CHRISTOPHE PETTUS HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.
# 
# CHRISTOPHE PETTUS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE. THE SOFTWARE PROVIDED HEREUNDER IS ON AN "AS IS" BASIS,
# AND CHRISTOPHE PETTUS HAS NO OBLIGATIONS TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
