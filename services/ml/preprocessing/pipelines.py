"""The candidate models, each a full scikit-learn pipeline (preprocessing included).

Keeping imputation, scaling and text vectorisation inside the pipeline means the exact same
preprocessing is saved with the model and applied at inference: nothing is refitted on the
data a prediction is made for.
"""

from typing import Final

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

TABULAR_CANDIDATES: Final = ("logistic_regression", "random_forest", "xgboost")
TEXT_CANDIDATES: Final = ("tfidf_logistic_regression", "tfidf_naive_bayes")


def tabular(name: str, *, n_classes: int, seed: int) -> Pipeline:
    if name == "logistic_regression":
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(max_iter=3000, C=0.5)),
            ]
        )
    if name == "random_forest":
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=5,
                        max_features="sqrt",
                        n_jobs=-1,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if name == "xgboost":
        # XGBoost handles missing values itself, so it gets the raw features.
        return Pipeline(
            [
                (
                    "clf",
                    XGBClassifier(
                        n_estimators=300,
                        max_depth=3,
                        learning_rate=0.05,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        objective="multi:softprob" if n_classes > 2 else "binary:logistic",
                        eval_metric="mlogloss" if n_classes > 2 else "logloss",
                        tree_method="hist",
                        n_jobs=4,
                        random_state=seed,
                    ),
                )
            ]
        )
    raise ValueError(f"unknown tabular candidate: {name}")


def text(name: str, *, seed: int) -> Pipeline:
    def features() -> FeatureUnion:
        return FeatureUnion(
            [
                ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                (
                    "chars",
                    TfidfVectorizer(
                        analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True
                    ),
                ),
            ]
        )

    if name == "tfidf_logistic_regression":
        return Pipeline(
            [
                ("tfidf", features()),
                ("clf", LogisticRegression(max_iter=3000, C=4.0, random_state=seed)),
            ]
        )
    if name == "tfidf_naive_bayes":
        return Pipeline([("tfidf", features()), ("clf", ComplementNB(alpha=0.3))])
    raise ValueError(f"unknown text candidate: {name}")
