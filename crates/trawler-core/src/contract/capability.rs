//! Required/optional capability negotiation (A22).

use std::collections::BTreeSet;

use super::error::QueryError;

/// A stable capability identifier plus its version.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Capability {
    pub name: String,
    pub version: u32,
}

impl Capability {
    #[must_use]
    pub fn new(name: impl Into<String>, version: u32) -> Self {
        Self {
            name: name.into(),
            version,
        }
    }
}

/// The set of capabilities a reader/engine implements.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilitySet {
    supported: BTreeSet<Capability>,
}

impl CapabilitySet {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn with(mut self, capability: Capability) -> Self {
        self.supported.insert(capability);
        self
    }

    pub fn insert(&mut self, capability: Capability) {
        self.supported.insert(capability);
    }

    #[must_use]
    pub fn supports(&self, capability: &Capability) -> bool {
        self.supported.contains(capability)
    }

    pub fn iter(&self) -> impl Iterator<Item = &Capability> {
        self.supported.iter()
    }
}

/// Required and optional capabilities attached to a request.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityRequest {
    pub required: Vec<Capability>,
    pub optional: Vec<Capability>,
}

impl CapabilityRequest {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// An unsupported *required* capability fails; unsupported optional
    /// capabilities are ignored.
    pub fn negotiate(&self, supported: &CapabilitySet) -> Result<(), QueryError> {
        for capability in &self.required {
            if !supported.supports(capability) {
                return Err(QueryError::UnsupportedCapability {
                    capability: capability.clone(),
                });
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capability_set_membership() {
        let mut set = CapabilitySet::new();
        assert!(!set.supports(&Capability::new("regex_query", 1)));
        set.insert(Capability::new("regex_query", 1));
        assert!(set.supports(&Capability::new("regex_query", 1)));
        assert!(!set.supports(&Capability::new("regex_query", 2)));
        assert_eq!(set.iter().count(), 1);
        let with = CapabilitySet::new().with(Capability::new("x", 1));
        assert_eq!(with.iter().count(), 1);
    }

    #[test]
    fn negotiation_rules() {
        let supported = CapabilitySet::new().with(Capability::new("a", 1));
        let request = CapabilityRequest {
            required: vec![Capability::new("a", 1)],
            optional: vec![Capability::new("b", 1)],
        };
        assert!(request.negotiate(&supported).is_ok());
        let missing = CapabilityRequest {
            required: vec![Capability::new("c", 1)],
            optional: vec![],
        };
        assert!(matches!(
            missing.negotiate(&supported),
            Err(QueryError::UnsupportedCapability { .. })
        ));
        assert!(CapabilityRequest::new().negotiate(&supported).is_ok());
    }
}
