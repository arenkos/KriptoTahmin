PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE realtime_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        symbol TEXT NOT NULL,
        trade_type TEXT NOT NULL,
        entry_price REAL NOT NULL,
        entry_time INTEGER NOT NULL,
        entry_balance REAL NOT NULL,
        exit_price REAL,
        exit_time INTEGER,
        exit_balance REAL,
        profit_loss REAL,
        trade_closed INTEGER NOT NULL
    );
INSERT INTO realtime_transactions VALUES(244398,'aren_32@hotmail.com','BTC/USDT','LONG',107497.8999999999942,X'20e0387997010000',100.0,107335.3000000000029,X'007b277997010000',-1038.199999999938882,-1138.199999999938882,1);
INSERT INTO realtime_transactions VALUES(244399,'aren_32@hotmail.com','BTC/USDT','SHORT',107335.3000000000029,X'a090267997010000',100.0,107092.1000000000058,X'e0c20e7997010000',1802.399999999979627,1702.399999999979627,1);
INSERT INTO realtime_transactions VALUES(244400,'aren_32@hotmail.com','BTC/USDT','LONG',107092.1000000000058,X'80d80d7997010000',100.0,106559.0,X'c0b0047997010000',-3631.700000000040746,-3731.700000000040746,1);
INSERT INTO realtime_transactions VALUES(244401,'aren_32@hotmail.com','BTC/USDT','SHORT',106559.0,X'60c6037997010000',100.0,106674.1999999999971,X'4015d57897010000',-706.3999999999796273,-806.3999999999796273,1);
INSERT INTO realtime_transactions VALUES(244402,'aren_32@hotmail.com','BTC/USDT','LONG',106674.1999999999971,X'e02ad47897010000',100.0,106690.1000000000058,X'401cbf7897010000',211.300000000061118,111.3000000000611181,1);
INSERT INTO realtime_transactions VALUES(244403,'aren_32@hotmail.com','BTC/USDT','SHORT',106690.1000000000058,X'e031be7897010000',100.0,106743.6999999999971,X'004bb27897010000',-275.1999999999388819,-375.1999999999388819,1);
INSERT INTO realtime_transactions VALUES(244404,'aren_32@hotmail.com','BTC/USDT','LONG',106743.6999999999971,X'a060b17897010000',100.0,106618.0,X'20b7ad7897010000',-779.8999999999796273,-879.8999999999796273,1);
INSERT INTO realtime_transactions VALUES(244405,'aren_32@hotmail.com','BTC/USDT','SHORT',106618.0,X'c0ccac7897010000',100.0,106745.0,X'e038a87897010000',-789.0,-889.0,1);
INSERT INTO realtime_transactions VALUES(244406,'aren_32@hotmail.com','BTC/USDT','LONG',106745.0,X'804ea77897010000',100.0,NULL,NULL,NULL,NULL,0);
COMMIT;
